"""Parent-side Git policy. Repository overrides must never redirect a caller."""
import os

HARDENING = ('-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false')
STRIPPED_ENV = ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR', 'GIT_INDEX_FILE',
                'GIT_EXTERNAL_DIFF', 'GIT_CONFIG_COUNT', 'GIT_CONFIG_PARAMETERS',
                'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES',
                'GIT_LITERAL_PATHSPECS', 'GIT_GLOB_PATHSPECS',
                'GIT_NOGLOB_PATHSPECS', 'GIT_ICASE_PATHSPECS')


def environment(source=None):
    env = {key: value for key, value in (os.environ if source is None else source).items()
           if key not in STRIPPED_ENV}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_OPTIONAL_LOCKS='0', GIT_TERMINAL_PROMPT='0')
    return env


def argv(repo, *args):
    return ['git', '-C', str(repo), *HARDENING, *args]
