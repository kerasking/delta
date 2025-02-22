# Copyright (C) 2017 Beijing Didi Infinity Technology and Development Co.,Ltd.
# All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
''' Stub post processing for speaker tasks. '''
import os
import collections
from absl import logging
import numpy as np

from delta.utils.postprocess.base_postproc import PostProc
from delta.utils.register import registers

#pylint: disable=too-many-instance-attributes
#pylint: disable=too-many-locals
#pylint: disable=too-many-nested-blocks
#pylint: disable=too-many-branches
#pylint: disable=too-few-public-methods


def format_kaldi_vector(vector):
  ''' Print a vector in Kaldi format. '''
  return '[ ' + ' '.join([str(val) for val in vector]) + ' ]'


@registers.postprocess.register
class SpeakerPostProc(PostProc):
  ''' Apply speaker embedding extraction on hidden layer outputs. '''

  def __init__(self, config):
    super().__init__(config)

    postconf = self.config['solver']['postproc']
    output_dir = postconf['pred_path']
    self.output_dir = output_dir if output_dir else os.path.join(
        self.config['solver']['saver']['model_path'], 'infer')
    if not os.path.exists(self.output_dir):
      os.makedirs(self.output_dir)

    self.log_verbose = postconf['log_verbose']

    self.eval = postconf['eval']
    self.infer = postconf['infer']

    self.stats = None
    self.confusion = None

    self.outputs = ['embeddings', 'softmax']
    self.output_files = collections.defaultdict(dict)
    for output_level in ['utt', 'chunk']:
      for output_key in self.outputs:
        output_file_name = '%s_%s.txt' % (output_level, output_key)
        self.output_files[output_level][output_key] = \
            os.path.join(self.output_dir, output_file_name)
    self.pred_metrics_path = os.path.join(self.output_dir, 'metrics.txt')

  # pylint: disable=arguments-differ
  def call(self, predictions, log_verbose=False):
    ''' Implementation of postprocessing. '''

    num_clips_processed = 0
    last_utt_key = None
    last_utt_chunk_outputs = {}
    for output_key in self.outputs:
      last_utt_chunk_outputs[output_key] = []
    if self.infer:
      file_pointers = collections.defaultdict(dict)
      for output_level in ['utt', 'chunk']:
        for output_key in self.outputs:
          file_pointers[output_level][output_key] = \
              open(self.output_files[output_level][output_key], 'w')

    for batch_index, batch in enumerate(predictions):
      # batch = {'inputs': [clip_0, clip_1, ...],
      #          'labels': [clip_0, clip_1, ...],
      #          'embeddings': [clip_0, clip_1, ...],
      #          ...}
      # Now we extract each clip from the minibatch.
      clips = collections.defaultdict(dict)
      for key, batch_values in batch.items():
        for clip_index, clip_data in enumerate(batch_values):
          clips[clip_index][key] = clip_data

      for clip_index, clip in sorted(clips.items()):
        if log_verbose or self.log_verbose:
          logging.debug(clip)
        chunk_key = clip['filepath'].decode()
        utt_key, utt_chunk_index_str = chunk_key.rsplit('_', 1)
        utt_chunk_index = int(utt_chunk_index_str[-2:])
        utt_chunk_index_from_clip_id = clip['clipid']
        assert utt_chunk_index == utt_chunk_index_from_clip_id

        for output_key in self.outputs:
          chunk_output = clip[output_key]
          if self.infer:
            formatted_output = format_kaldi_vector(chunk_output)
            file_pointers['chunk'][output_key].write(
                '%s %s\n' % (chunk_key, formatted_output))

          embeddings = last_utt_chunk_outputs[output_key]
          # Check if an utterance is over.
          if utt_key != last_utt_key:
            if last_utt_key is not None:
              # Average over all chunks.
              logging.debug('Utt %s: averaging "%s" over %d chunks' %
                            (last_utt_key, output_key, len(embeddings)))
              utt_embedding = np.average(embeddings, axis=0)
              if self.infer:
                formatted_output = format_kaldi_vector(utt_embedding)
                file_pointers['utt'][output_key].write(
                    '%s %s\n' % (last_utt_key, formatted_output))

            # Start a new utterance.
            embeddings.clear()
          embeddings.append(chunk_output)
        last_utt_key = utt_key

      num_clips_processed += len(clips)
      if (batch_index + 1) % 10 == 0:
        logging.info('Processed %d batches, %d clips.' %
                     (batch_index + 1, num_clips_processed))

    # Average over all chunks for the last utterance.
    # TODO: reusability
    for output_key in self.outputs:
      embeddings = last_utt_chunk_outputs[output_key]
      # Average over all chunks.
      logging.debug('Utt %s: averaging "%s" over %d chunks' %
                    (last_utt_key, output_key, len(embeddings)))
      utt_embedding = np.average(embeddings, axis=0)
      if self.infer:
        formatted_output = format_kaldi_vector(utt_embedding)
        file_pointers['utt'][output_key].write('%s %s\n' %
                                               (last_utt_key, formatted_output))

    if self.infer:
      for output_level in ['utt', 'chunk']:
        for output_key in self.outputs:
          file_pointers[output_level][output_key].close()

    logging.info('Postprocessing completed.')
