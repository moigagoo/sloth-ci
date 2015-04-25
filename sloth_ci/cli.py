'''Sloth CI.

Usage:
    sloth-ci (start | restart | stop | status ) [-c <file>]
    sloth-ci create <config_paths>... [-c <file>]
    sloth-ci remove <listen_points>... [-c <file>]
    sloth-ci trigger <listen_point> [-p <params>] [-c <file>]
    sloth-ci (info | list | reload) [<listen_points>...] [-c <file>]
    sloth-ci logs <listen_point> [--from-page <number>] [--to-page <number>] [--per-page <number>] [--level   <number>] [-c <file>]
    sloth-ci history <listen_point> [--from-page <number>] [--to-page <number>] [--per-page <number>] [-c <file>]
    sloth-ci --version
    sloth-ci --help

Options:
    -c <file>, --config <file>    Path to the server config file [default: ./sloth.yml]
    -p --params <params>          Params to trigger the actions with. String like 'param1=val1,param2=val2'
    --from-page <number>          The first page.
    --to-page <number>            The last page.
    --per-page <number>           Number of records per page.
    --level <number>              Minimal numeric logging level to be included in the output.
    -v --version                  Show version
    -h --help                     Show this screen

'''


from sys import exit

from os.path import abspath, isfile
from glob import glob 
from time import ctime

from docopt import docopt
from tabulate import tabulate
from yaml import load

from . import __version__
from .bed import Bed
from .api.client import API


def colorize(table):
    '''Colorize logs table according to message status.

    :param table: logs table, each row is [timestamp, message, level_name]

    :returns: colorized table
    '''

    colorized_table = []

    from colorama import init, deinit, Fore, Back

    init()

    for row in table:
        level_name = row[2]

        if level_name == 'DEBUG':
            color = Fore.CYAN
        elif level_name == 'INFO':
            color = Fore.GREEN
        elif level_name == 'WARNING':
            color = Fore.YELLOW
        elif level_name == 'ERROR':
            color = Fore.RED
        elif level_name == 'CRITICAL':
            color = Fore.RED + Back.WHITE

        reset = Fore.RESET + Back.RESET

        colorized_table.append(list(map(lambda cell: color + cell + reset, row)))

    return colorized_table


class CLI:
    def __init__(self, config_file):
        if not isfile(config_file):
            print('Either put "sloth.yml" in this directory or pick a config file with "-c."')
            exit()
        
        try:
            self.config = load(open(config_file))
            
            self.api = API(self.config)

        except Exception as e:
            print('Failed to parse the config file: %s' % e)
            exit()

        self.actions = {
            'start': self.start,
            'create': self.create,
            'remove': self.remove,
            'trigger': self.trigger,
            'reload': self.reload,
            'status': self.status,
            'info': self.info,
            'list': self.info,
            'logs': self.logs,
            'history': self.history,
            'restart': self.restart,
            'stop': self.stop
        }

    def start(self, args):
        '''Start a Sloth CI server.'''

        try:
            print('Starting Sloth CI on %s' % self.api.url)
            Bed(self.config).start()

        except Exception as e:
            print('Failed to start Sloth CI: %s' % e)

    def create(self, args):
        '''Create apps from config files and bind them with respective files.'''

        for config_path in args['<config_paths>']:
            config_files = glob(config_path)

            if not config_files:
                print('Path %s not found' % config_path)
                continue

            for config_file in config_files:
                try:
                    listen_point = self.api.create(abspath(config_file))
                    print('App created on %s' % listen_point)

                except Exception as e:
                    print('Failed to create app: %s' % e)
                    continue

                try:
                    self.api.bind(listen_point, abspath(config_file))
                    print('App on %s bound with config file %s' % (listen_point, config_file))

                except Exception as e:
                    print('Failed to bind app on %s with config file %s: %s' % (listen_point, config_file, e))

    def remove(self, args):
        '''Remove apps on listen points.'''

        for listen_point in args['<listen_points>']:
            try:
                self.api.remove(listen_point)
                print('App on %s removed' % listen_point)

            except Exception as e:
                print('Failed to remove app on %s: %s' % (listen_point, e))

    def trigger(self, args):
        '''Trigger app actions on a listen point.'''

        try:
            listen_point = args['<listen_point>']
            params = {}

            if args['--params']:
                params.update(dict((pair.split('=') for pair in args['--params'].split(','))))

            self.api.trigger(listen_point, params)
            print('Actions triggered on %s' % listen_point)

        except Exception as e:
            print('Failed to trigger actions on %s: %s' % (listen_point, e))

    def info(self, args):
        '''Get information about certain or all apps.'''

        try:
            apps = self.api.info(args['<listen_points>'])
            
            table = [
                [
                    app['listen_point'],
                    app['config_file'],
                    app['last_build_status'],
                    ctime(app['last_build_timestamp'])
                ] for app in apps
            ]
            
            print(tabulate(table, headers=[
                'Listen Point',
                'Config File',
                'Last Build Status',
                'Last Build Timestamp'
            ]))

        except Exception as e:
            print('Failed to get app info: %s' % e)

    def logs(self, args):
        '''Get app logs.'''

        try:
            logs = self.api.logs(
                args['<listen_point>'],
                args['--from-page'],
                args['--to-page'],
                args['--per-page'],
                args['--level']
            )

            table = [
                [
                    ctime(record['timestamp']),
                    record['message'],
                    record['level_name']
                ] for record in logs
            ]

            print(tabulate(colorize(table), headers=['Timestamp', 'Message', 'Level']))

        except Exception as e:
            print('Failed to get app logs: %s' % e)

    def history(self, args):
        '''Get app build history.'''

        try:
            history = self.api.history(
                args['<listen_point>'],
                args['--from-page'],
                args['--to-page'],
                args['--per-page']
            )

            table = [
                [
                    ctime(record['timestamp']),
                    record['message']
                ] for record in history
            ]

            print(tabulate(table, headers=['Timestamp', 'Status']))

        except Exception as e:
            print('Failed to get app logs: %s' % e)

    def reload(self, args):
        '''Reload certain or all apps, i.e. remove, recreate, and rebind them with the config files.'''

        try:
            app_list = self.api.info()

        except ConnectionError as e:
            print('Failed to reload apps: %s' % e)
            exit()

        reload_list = args['<listen_points>'] or [app['listen_point'] for app in app_list]

        for listen_point in reload_list:
            try:
                config_file = self.api.info([listen_point])[0]['config_file']

                if not config_file:
                    raise FileNotFoundError('The app is not bound with a config file')
                
                self.api.remove(listen_point)
                new_listen_point = self.api.create(config_file)
                self.api.bind(new_listen_point, config_file)

                print('App on %s reloaded' % listen_point)

            except Exception as e:
                print('Failed to reload app on %s: %s' % (listen_point, e))

    def status(self, args):
        '''Get Sloth CI server status (running or not running).'''

        try:
            version = self.api.version()
            print('Sloth CI version %s is running on %s' % (version, self.api.url))

        except:
            print('Sloth CI is not running on %s' % self.api.url)

    def restart(self, args):
        '''Ask a Sloth CI server to restart.'''

        try:
            self.api.restart()
            print('Restarting Sloth CI on %s ' % self.api.url)

        except Exception as e:
            print('Failed to restart Sloth CI on %s: %s' % (self.api.url, e))

    def stop(self, args):
        '''Ask a Sloth CI server to stop.'''

        try:
            self.api.stop()
            print('Stopping Sloth CI on %s ' % self.api.url)

        except Exception as e:
            print('Failed to stop Sloth CI on %s: %s' % (self.api.url, e))


def main():
    args = docopt(__doc__, version=__version__)

    cli = CLI(args['--config'])

    action = [key for key, value in args.items() if value == True][0]

    cli.actions[action](args)
