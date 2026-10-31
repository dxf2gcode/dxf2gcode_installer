"""File-system adapter for legacy project text."""


class LegacyProjectFileStore:
    """Read and write project text using the existing platform encoding."""

    def read_text(self, filename):
        with open(filename, "r") as project_file:
            return project_file.read()

    def write_text(self, filename, content):
        with open(filename, "w") as project_file:
            project_file.write(content)

