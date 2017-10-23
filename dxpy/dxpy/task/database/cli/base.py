class CLI(click.MultiCommand):
    """
    Task database utils.
    """
    commands = {'start', None}

    def __init__(self):
        super(__class__, self).__init__(name='db', help=__class__.__doc__)

    def list_commands(self, ctx):
        return sorted(self.commands.keys())

    def get_command(self, ctx, name):
        from . import commands
        if name in self.commands:
            if self.commands[name] is None:
                self.commands[name] = commands.get(name)
        return self.commands.get(name)


main = CLI()