class MarkdownRenderer:
    def render(self, title, body):
        return '# %s\n\n%s' % (title, body)
