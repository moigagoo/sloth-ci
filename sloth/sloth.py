"""
**************
sloth.Sloth
**************

This module contains the :class:`Sloth <Sloth>` class.
"""


from subprocess import Popen, TimeoutExpired
from argparse import ArgumentParser
from json import loads
from threading import Thread

import logging

import cherrypy
import requests
import configs


class Sloth:
    """Main Sloth class.

    Each instance represents a separate sloth app,
    with its own config, log, action queue, and queue processor.

    Each app listens for incoming requests on its own URL path.
    """

    def __init__(self, config):
        self.config = config

        self.name = self.config.config_file.split('.')[0]

        file_handler = logging.FileHandler(self.name + '.log', 'a+')
        formatter = logging.Formatter(
            '%(asctime)s | %(name)20s | %(levelname)10s | %(message)s'
        )
        file_handler.setFormatter(formatter)

        self.logger = logging.getLogger(self.name)
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(file_handler)

        self.processing_logger = self.logger.getChild('processing')

        self.queue = []
        self.queue_lock = False

        self.queue_processor = Thread(target=self.process_queue, name=self.name)
        self._processor_lock = False

        self.queue_processor.start()


    def validate_bb_payload(self, payload):
        """Validate Bitbucket payload against repo name and branch.

        :param payload: payload to be validated

        :returns: True of the payload is valid, False otherwise
        """

        try:
            parsed_payload = loads(payload)

            repo = parsed_payload['repository']['owner'] + '/' + parsed_payload['repository']['slug']
            branch = parsed_payload['commits'][-1]['branch']

            if repo == self.config['repo'] and branch == self.config['branch']:
                self.processing_logger.info('Payload validated')
                return True
            elif repo != self.config['repo']:
                self.processing_logger.info('Payload validation failed: repo mismatch.')
                return False
            elif branch != self.config['branch']:
                self.processing_logger.info('Payload validation failed: branch mismatch.')
                return False
        except:
            self.processing_logger.info('Payload validation failed.')
            return False

    def execute(self, action):
        """Executes command line command.

        :param action: action to be executed

        :returns: True if successful, Exception otherwise
        """

        self.processing_logger.info('Executing action: %s', action)

        try:
            process = Popen(action.split(), cwd=self.config['work_dir']).wait()

            self.processing_logger.info('Action executed: %s', action)
            return True

        except TimeoutExpired as e:
            self.processing_logger.critical('Action timed out: %s', e)
            return e

        except Exception as e:
            self.processing_logger.critical('Action failed: %s', e)
            return e

    def broadcast(self, payload, node):
        """Transmit payload to a node.

        :param payload: payload to be transmitted
        :param node: complete node URL (with protocol and port, **with** the path to the sloth listener)

        :returns: response code
        """

        try:
            r = requests.post('%s' % node, data={'payload': payload, 'orig': False})

            if r.status_code == 200:
                self.processing_logger.info('Payload broadcasted to %s', node)
            else:
                self.processing_logger.warning('Broadcasting to %s failed: %s', node, r.status)

            return True
        except Exception as e:
            self.processing_logger.warning('Broadcasting to %s failed: %s', node, e)
            return e

    def process_queue(self):
        """Processes execution queue in a separate thread."""

        while not self._processor_lock:
            if self.queue:
                payload, orig = self.queue.pop(0)

                if self.config['actions']:
                    for action in self.config['actions']:
                        self.execute(action)

                if orig and self.config['nodes']:
                    for node in self.config['nodes']:
                        self.broadcast(payload, node)

            elif self.queue_lock:
                return True

            else:
                pass

    def stop(self):
        """Gracefully stops the queue processor.

        New payloads are not added to the queue, existing actions will be finished.
        """
        self.queue_lock = True
        self.logger.info('Stopped.')

    def kill(self):
        """Immediatelly stops the queue processor and clears the queue."""

        self.stop()

        self._processor_lock = True
        self.logger.warning('Killed.')
