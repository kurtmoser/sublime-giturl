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
        'line_range': '#L{line}-L{line_end}'
    },
    'bitbucket.org': {
        'url': 'https://{domain}/{user}/{repo}/src/{revision}/{path}',
        'line': '#lines-{line}',
        'line_range': '#lines-{line}:{line_end}'
    },
    'gitlab.com': {
        'url': 'https://{domain}/{user}/{repo}/blob/{revision}/{path}',
        'line': '#L{line}',
        'line_range': '#L{line}-{line_end}'
    },
}

def plugin_unloaded():
    remove_context_menu_file()

def remove_context_menu_file():
    plugin_path = os.path.dirname(__file__)
    menu_file = os.path.join(plugin_path, 'Context.sublime-menu')

    try:
        os.remove(menu_file)
    except FileNotFoundError:
        pass

class GiturlEventListener(sublime_plugin.EventListener):
    def on_activated_async(self, view):
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

        self.create_context_menu(repo_data)

    def get_local_repodir(self, dirname):
        cmd = 'git rev-parse --show-toplevel'
        local_repodir = self.get_exec_response(cmd, dirname)
        return local_repodir

    def get_remote_origin(self, dirname):
        cmd = 'git config --list'
        return_lines = self.get_exec_response(cmd, dirname).split('\n')
        for line in return_lines:
            if line[0:len('remote.origin.url=')] == 'remote.origin.url=':
                remote_origin = line[len('remote.origin.url='):]
                return remote_origin

    def get_default_branch_name(self, dirname):
        cmd = 'git symbolic-ref refs/remotes/origin/HEAD | sed \'s@^refs/remotes/origin/@@\''
        default_branch = self.get_exec_response(cmd, dirname)
        return default_branch

    def get_current_branch_name(self, dirname):
        cmd = 'git rev-parse --abbrev-ref HEAD'
        current_branch = self.get_exec_response(cmd, dirname)
        return current_branch

    def get_current_commit_hash(self, dirname, filename):
        cmd = 'git rev-list -1 HEAD ' + filename
        commit_hash = self.get_exec_response(cmd, dirname)
        return commit_hash

    def get_exec_response(self, cmd, dirname):
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, cwd=dirname)
        proc_return = proc.stdout.read()
        return proc_return.decode().strip()

    def parse_remote_origin(self, remote_origin):
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

    def create_context_menu(self, repo_data):
        plugin_path = os.path.dirname(__file__)
        menu_file = os.path.join(plugin_path, 'Context.sublime-menu')

        with open(menu_file, 'w') as f:
            contextmenu = [
                {
                    'caption': 'Open Commit Url...',
                    'command': 'giturl_browse',
                    'id': '~giturl_1',
                    'args': {
                        'url_type': 'current_commit',
                        'repo_data': repo_data,
                    },
                },
            ]

            if repo_data['current_branch'] != repo_data['default_branch']:
                contextmenu.extend([
                    {
                        'caption': 'Open Branch Url...',
                        'command': 'giturl_browse',
                        'id': '~giturl_2',
                        'args': {
                            'url_type': 'current_branch',
                            'repo_data': repo_data,
                        },
                    },
                    {
                        'caption': 'Open Default Branch Url...',
                        'command': 'giturl_browse',
                        'id': '~giturl_3',
                        'args': {
                            'url_type': 'default_branch',
                            'repo_data': repo_data,
                        },
                    },
                ])
            else:
                contextmenu.extend([
                    {
                        'caption': 'Open Branch Url...',
                        'command': 'giturl_browse',
                        'id': '~giturl_2',
                        'args': {
                            'url_type': 'default_branch',
                            'repo_data': repo_data,
                        },
                    }
                ])

            json.dump(contextmenu, f)

class GiturlBrowseCommand(sublime_plugin.TextCommand):
    def run(self, edit, **kwargs):
        global giturl_domains

        url_type = kwargs['url_type']
        repo_data = kwargs['repo_data']

        repo_data['revision'] = repo_data[url_type]

        if repo_data['domain'] in giturl_domains:
            domain_key = repo_data['domain']
        else:
            domain_key = 'github.com'

        if url_type == 'current_commit' and 'url_commit' in giturl_domains[domain_key]:
            browse_url = giturl_domains[domain_key]['url_commit']
        elif url_type == 'current_branch' and 'url_branch' in giturl_domains[domain_key]:
            browse_url = giturl_domains[domain_key]['url_branch']
        else:
            browse_url = giturl_domains[domain_key]['url']

        repo_data['line'] = self.view.rowcol(self.view.sel()[0].begin())[0] + 1
        line_end = self.view.rowcol(self.view.sel()[0].end())[0] + 1
        if line_end > repo_data['line'] and self.view.rowcol(self.view.sel()[0].end())[1] == 0:
            line_end -= 1

        if line_end == repo_data['line']:
            browse_url += giturl_domains[domain_key]['line']
        else:
            browse_url += giturl_domains[domain_key]['line_range']
            repo_data['line_end'] = line_end

        for key in repo_data:
            browse_url = browse_url.replace('{' + str(key) + '}', str(repo_data[key]))

        webbrowser.open_new_tab(browse_url)
