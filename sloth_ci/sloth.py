from subprocess import Popen, PIPE
from threading import Thread
from os.path import splitext, basename, abspath, join
from collections import deque
from importlib import import_module

from cherrypy import HTTPError

import logging


class Sloth:
    '''Base Sloth class.

    Each instance represents a separate Sloth app,
    with its own config, log, action queue, and queue processor.

    Each app listens for incoming requests on its own URL path.
    '''

    def __init__(self, config):
        self.config = config

        self.listen_point = self.config['listen_point']
        
        self.logger = logging.getLogger(self.listen_point)
        self.logger.setLevel(logging.DEBUG)

        self.build_logger = self.logger.getChild('build')
        self.exec_logger = self.logger.getChild('exec')
        
        self.log_handlers = {}

        self.queue = deque()
        self._queue_lock = False

        self.queue_processor = None
        self._processing_lock = False

    @classmethod
    def extend(cls, extensions):
        '''Sequentially chain-inherit Sloth classes from extensions.
    
        The first extension's Sloth class inherits from the base Sloth class and becomes the base class, then the second one inherits from it, and so on.

        :param extensions: list of extensions to load.
    
        :returns: ExtendedSloth is a Sloth class inherited from all extensions' Sloth classes; errors—list of errors raised during the extensions loading.
        '''
    
        ExtendedSloth = cls
        errors = []

        if extensions:
            for extension_name, extension_config in extensions.items():
                try:
                    ext = import_module('.ext.%s' % extension_config['module'], package=__package__)
            
                    ExtendedSloth = ext.extend(ExtendedSloth, {
                            'name': extension_name,
                            'config': extension_config
                        }
                    )

                except Exception as e:
                    errors.append('Could not load extension %s: %s' % (extension_name, e))

        return ExtendedSloth, errors

    def handle(self, request):
        '''Validate, extract, and process incoming payload.
        
        :param request: a cherrypy.request instance
        '''

        self.logger.debug('Payload received from %s - %s' % (
                request.remote.ip,
                request.headers['User-Agent']
            )
        )

        try:
            provider_section = self.config.get('provider')

            if provider_section:
                provider, provider_data = provider_section.copy().popitem()

            else:
                raise HTTPError(400, 'No provider set, declining all payloads')

            validator = import_module('.validators.%s' % provider, package=__package__)

        except ImportError as e:
            self.logger.critical('No matching validator found: %s' % e)
            raise HTTPError(500, 'No matching validator found: %s' % e)

        validation_data = provider_data or {}

        status, message, param_dicts = validator.validate(request, validation_data)

        self.logger.debug(message)

        if status == 200:
            self.logger.info('Valid payload received')
                
        else:
            raise HTTPError(status, message)

        for params in param_dicts:
            self.process(params)

    def process(self, validator_params):
        '''Queue execution of actions with certain params. 
        
        Params are taken from the ``params`` config section and extracted from the incoming payload.
        
        :param validator_params: params exctacted from the payload
        '''

        params = dict(self.config.get('params', {}), **validator_params)

        if not self._queue_lock:
            self.queue.append(params)
        
        if not self.queue_processor or not self.queue_processor.is_alive():
            self.queue_processor = Thread(target=self.process_queue, name=self.listen_point)
            self.queue_processor.start()

    def process_queue(self):
        '''Processes execution queue in a separate thread.
        
        :returns: True if successful, exception otherwise
        '''

        actions = self.config.get('actions')
        
        status = 'Complete'

        if actions:
            while self.queue:
                if self._processing_lock:
                    self.exec_logger.warning('Queue processing interrupted')
                    break

                params = self.queue.popleft()

                try:
                    self.run_build(actions, params)

                except:
                    pass

        return True

    def run_build(self, actions, params):
        '''Run a build with the given params.

        :param actions: actions in this build
        :param params: params used by the actions

        :returns: True if successful, exception otherwise
        '''

        errors = []

        self.build_logger.debug('Triggered, actions in queue: %d' % len(actions))

        self.exec_logger.debug('Params: %s' % params)

        for action in actions:
            try:
                action_with_params = action.format_map(params)

                self.exec_logger.info('Executing action: %s' % action_with_params)

                self.execute(action_with_params)

            except KeyError as e:
                self.exec_logger.error('Missing param: %s' % e)
                errors.append(e)

            except Exception as e:
                self.exec_logger.error('Execution failed: %s' % e)
                errors.append(e)

            finally:
                if errors and self.config.get('stop_on_first_fail'):
                    self.build_logger.error('Failed on action "%s": %s' % (action, errors[0]))
                    raise errors[0]
        
        if not errors:
            self.build_logger.info('Completed %d/%d' % (len(actions), len(actions)))

        elif len(errors) == len(actions):
            self.build_logger.warning('None completed: %d/%d' % (len(actions) - len(errors), len(actions)))

        else:
            self.build_logger.warning('Partially completed: %d/%d' % (len(actions) - len(errors), len(actions)))

    def execute(self, action):
        '''Executes an action in an ordinary Popen.

        :param action: action to be executed

        :returns: True if successful, exception otherwise
        '''

        try:
            process = Popen(
                action,
                shell=True,
                cwd=self.config.get('work_dir') or '.',
                stdout=PIPE,
                stderr=PIPE
            )

            stdout, stderr = process.communicate(timeout=self.config.get('exec_timeout'))

            self.exec_logger.debug('stdout: %s' % bytes.decode(stdout))
            self.exec_logger.debug('stderr: %s' % bytes.decode(stderr))

            if process.returncode:
                raise RuntimeError('Exit code: %d' % process.returncode)

            self.exec_logger.info('Finished')
            
            return True

        except Exception:
            raise

    def stop(self):
        '''Gracefully stop the queue processor.

        New payloads are not added to the queue, existing actions will be finished.
        '''

        self._queue_lock = True
        self.logger.info('Stopped')

    def kill(self):
        '''Immediately stop processing the queue.'''

        self.stop()

        self._processing_lock = True
        self.logger.warning('Killed')
