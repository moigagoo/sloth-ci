"""
***********
sloth.api
***********

This module implements the Sloth API.
"""

import cherrypy

from .sloth import Sloth

def make_listener(sloth)

    @cherrypy.expose
    def listener(payload, orig=True):

        if not cherrypy.request.method == 'POST':
            raise cherrypy.HTTPError(405)

        if not sloth.validate_bb_payload(payload):
            raise cherrypy.HTTPError(400)

        sloth.logger.info('Payload received')

        if not sloth.queue_lock:
            sloth.queue.append((payload, orig))

    return listener


def run(server_config, sloths):
    """Runs CherryPy loop to listen for payload."""

    cherrypy.config.update({
        'server.socket_host': server_config['host'],
        'server.socket_port': server_config['port']
        })

    for sloth in sloths:
        cherrypy.tree.mount(make_listener(sloth), sloth.config['listen_to'])
        sloth.logger.info('Mounted')

        cherrypy.engine.autoreload.files.add(sloth.config.config_file)

        cherrypy.engine.subscribe('stop', sloth.stop)

        cherrypy.engine.start()
        cherrypy.engine.block()

def main():

    parser = ArgumentParser()
    parser.add_argument('configs', nargs='+')

    config_files = parser.parse_args().configs
    sloths = [Sloth(configs.load(_, 'default.conf')) for _ in config_files]

    server_config = configs.load('server.conf')

    run(server_config, sloths)

if __name__ == '__main__':
    main()
