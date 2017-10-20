#!/home/hongxwing/anaconda3/bin/python
import click


class CLI(click.MultiCommand):
    commands = {'code': None, 'task': None, 'batch': None}

    def __init__(self):
        super(__class__, self).__init__(name='dxl', help='DXL CLI tools.')

    def list_commands(self, ctx):
        return sorted(self.commands.keys())

    def get_command(self, ctx, name):
        from ..task.cli import task
        from ..code.cli import code
        from ..batch.cli import batch
        if name in self.commands:
            if self.commands[name] is None:
                mapping = {
                    'code': code,
                    'task': task,
                    'batch': batch
                }
                self.commands[name] = mapping.get(name)
        return self.commands.get(name)


dxl = CLI()

if __name__ == "__main__":
    dxl()
