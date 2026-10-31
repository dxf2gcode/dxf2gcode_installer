"""ConfigObj-backed storage used by the legacy configuration models."""

from configobj import ConfigObj


class ConfigObjStore:
    """Keep ConfigObj file access behind an injectable adapter boundary."""

    def read(self, filename, configspec):
        return ConfigObj(filename, configspec=configspec)

    def spec(self, text):
        return ConfigObj(text, interpolation=False, list_values=False,
                         _inspec=True)

    def defaults(self, configspec):
        return ConfigObj(configspec=configspec)

    def write(self, config, filename):
        config.filename = filename
        config.write()
