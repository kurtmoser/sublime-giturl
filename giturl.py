import json
import os
import re
import sublime
import sublime_plugin
import subprocess
import webbrowser

giturl_domains = {
    'github.com': {
        'url': 'https://{domain}/{user}/{repo}/blob/{revision}/{path}',
        'line': '#L{line}',
        'line_range': '#L{line}-L{line_end}',
    },
    'bitbucket.org': {
        'url': 'https://{domain}/{user}/{repo}/src/{revision}/{path}',
        'line': '#lines-{line}',
        'line_range': '#lines-{line}:{line_end}',
    },
    'gitlab.com': {
        'url': 'https://{domain}/{user}/{repo}/blob/{revision}/{path}',
        'line': '#L{line}',
        'line_range': '#L{line}-{line_end}',
    },
    '_bitbucket_selfhosted': {
        'url': 'https://{domain}/projects/{user}/repos/{repo}/browse/{path}',
        'url_commit': 'https://{domain}/projects/{user}/repos/{repo}/browse/{path}?at={revision}',
        'url_branch': 'https://{domain}/projects/{user}/repos/{repo}/browse/{path}?at=refs/heads/{revision}',
        'line': '#{line}',
        'line_range': '#{line}-{line_end}',
    },
}

# Store repo data globally so that commands don't need additional data passed
# to them. This is not the best solution but it simplifies binding keyboard
# shortcuts to commands.
repo_data = {}

def plugin_unloaded():
    remove_context_menu_file()

def remove_context_menu_file():
    """Remove Sublime context menu items"""

    plugin_path = os.path.dirname(__file__)
    menu_file = os.path.join(plugin_path, 'Context.sublime-menu')

    try:
        os.remove(menu_file)
    except FileNotFoundError:
        pass

class GiturlEventListener(sublime_plugin.EventListener):
    def on_activated_async(self, view):
        global repo_data

        repo_data = {}

        settings = sublime.load_settings("GitUrl.sublime-settings")
        user_domains = settings.get("domains", {})
        for domain in user_domains:
            giturl_domains[domain] = user_domains[domain]

        remove_context_menu_file()

        if not view.file_name():
            return

        local_repodir = self.get_local_repodir(os.path.dirname(view.file_name()))
        if not local_repodir:
            return

        relative_filepath = view.file_name()[(len(local_repodir) + 1):]

        remote_origin = self.get_remote_origin(local_repodir)
        if not remote_origin:
            return

        remote_origin_parts = self.parse_remote_origin(remote_origin)

        default_branch = self.get_default_branch_name(local_repodir)
        current_branch = self.get_current_branch_name(local_repodir)
        current_commit = self.get_current_commit_hash(local_repodir, relative_filepath)

        repo_data = {
            'domain': remote_origin_parts['domain'],
            'user': remote_origin_parts['user'],
            'repo': remote_origin_parts['repo'],
            'path': relative_filepath,

            'current_commit': current_commit,
            'current_branch': current_branch,
            'default_branch': default_branch,
        }

        self.create_context_menu()

    def get_local_repodir(self, dirname):
        """Get git repo local root directory"""

        cmd = 'git rev-parse --show-toplevel'
        local_repodir = self.get_exec_response(cmd, dirname)
        return local_repodir

    def get_remote_origin(self, dirname):
        """Get git repo remote origin"""

        cmd = 'git config --list'
        return_lines = self.get_exec_response(cmd, dirname).split('\n')
        for line in return_lines:
            if line[0:len('remote.origin.url=')] == 'remote.origin.url=':
                remote_origin = line[len('remote.origin.url='):]
                return remote_origin

    def get_default_branch_name(self, dirname):
        """Get git repo default branch name"""

        cmd = 'git symbolic-ref refs/remotes/origin/HEAD'
        default_branch = self.get_exec_response(cmd, dirname)
        return re.sub('^refs/remotes/origin/', '', default_branch)

    def get_current_branch_name(self, dirname):
        """Get git repo current branch name"""

        cmd = 'git rev-parse --abbrev-ref HEAD'
        current_branch = self.get_exec_response(cmd, dirname)
        return current_branch

    def get_current_commit_hash(self, dirname, filename):
        """Get git repo file latest commit hash"""

        cmd = 'git rev-list -1 HEAD ' + filename
        commit_hash = self.get_exec_response(cmd, dirname)
        return commit_hash

    def get_exec_response(self, cmd, dirname):
        """Execute shell command and return response"""

        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, cwd=dirname)
        proc_return = proc.stdout.read()
        return proc_return.decode().strip()

    def parse_remote_origin(self, remote_origin):
        """Split git remote origin string into parts"""

        parts = re.match('^[^:]+://([^/]+)/.*?([^/]+)/([^/]+).git$', remote_origin)
        if parts:
            return {
                'domain': parts.group(1),
                'user': parts.group(2).lstrip('~'),
                'repo': parts.group(3),
            }

        parts = re.match('^[^@]+@([^:]+):.*?([^/]+)/([^/]+).git$', remote_origin)
        if parts:
            return {
                'domain': parts.group(1),
                'user': parts.group(2).lstrip('~'),
                'repo': parts.group(3),
            }

    def create_context_menu(self):
        """Create Sublime context menu items"""

        global repo_data

        plugin_path = os.path.dirname(__file__)
        menu_file = os.path.join(plugin_path, 'Context.sublime-menu')

        with open(menu_file, 'w') as f:
            contextmenu = [
                {
                    'caption': 'Open Commit Url...',
                    'command': 'giturl_open_commit',
                    'id': '~giturl_1',
                },
            ]

            if repo_data['current_branch'] != repo_data['default_branch']:
                contextmenu.extend([
                    {
                        'caption': 'Open Branch Url...',
                        'command': 'giturl_open_branch',
                        'id': '~giturl_2',
                    },
                    {
                        'caption': 'Open Default Branch Url...',
                        'command': 'giturl_open_default_branch',
                        'id': '~giturl_3',
                    },
                ])
            else:
                contextmenu.extend([
                    {
                        'caption': 'Open Branch Url...',
                        'command': 'giturl_open_default_branch',
                        'id': '~giturl_2',
                    }
                ])

            json.dump(contextmenu, f)

class GiturlOpenCommitCommand(sublime_plugin.TextCommand):
    def run(self, edit, **kwargs):
        global repo_data

        if not len(repo_data):
            return

        url_generator = UrlGenerator()
        url = url_generator.generate_url(self.view, 'current_commit', repo_data)
        webbrowser.open_new_tab(url)

class GiturlOpenBranchCommand(sublime_plugin.TextCommand):
    def run(self, edit, **kwargs):
        global repo_data

        if not len(repo_data):
            return

        url_generator = UrlGenerator()
        url = url_generator.generate_url(self.view, 'current_branch', repo_data)
        webbrowser.open_new_tab(url)

class GiturlOpenDefaultBranchCommand(sublime_plugin.TextCommand):
    def run(self, edit, **kwargs):
        global repo_data

        if not len(repo_data):
            return

        url_generator = UrlGenerator()
        url = url_generator.generate_url(self.view, 'default_branch', repo_data)
        webbrowser.open_new_tab(url)

class UrlGenerator():
    def generate_url(self, view, url_type, repo_data):
        """Generate git repo browse url"""

        self.view = view
        line_start, line_end = self.get_selected_lines()
        repo_data['revision'] = repo_data[url_type]
        repo_data['line'] = line_start
        repo_data['line_end'] = line_end

        if repo_data['domain'] in giturl_domains:
            domain_key = repo_data['domain']
        else:
            domain_key = '_bitbucket_selfhosted'

        url = self.get_url_pattern(url_type, domain_key, line_start, line_end)
        return self.fill_url_pattern(url, repo_data)

    def get_url_pattern(self, url_type, domain_key, line_start, line_end):
        """Get git repo url pattern"""

        global giturl_domains

        if url_type == 'current_commit' and 'url_commit' in giturl_domains[domain_key]:
            browse_url = giturl_domains[domain_key]['url_commit']
        elif url_type == 'current_branch' and 'url_branch' in giturl_domains[domain_key]:
            browse_url = giturl_domains[domain_key]['url_branch']
        else:
            browse_url = giturl_domains[domain_key]['url']

        if line_end != line_start and 'line_range' in giturl_domains[domain_key]:
            browse_url += giturl_domains[domain_key]['line_range']
        elif 'line' in giturl_domains[domain_key]:
            browse_url += giturl_domains[domain_key]['line']

        return browse_url

    def fill_url_pattern(self, url, repo_data):
        """Fill git repo url pattern with repo data"""

        for key in repo_data:
            url = url.replace('{' + str(key) + '}', str(repo_data[key]))
        return url

    def get_selected_lines(self):
        """Get selected/active lines in editor"""

        line_start = self.view.rowcol(self.view.sel()[0].begin())[0] + 1
        line_end = self.view.rowcol(self.view.sel()[0].end())[0] + 1
        col_end = self.view.rowcol(self.view.sel()[0].end())[1]

        if line_end > line_start and col_end == 0:
            line_end -= 1

        return (line_start, line_end)
