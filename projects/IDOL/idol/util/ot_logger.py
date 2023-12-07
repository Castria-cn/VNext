from collections import defaultdict

class OneTimeLogger:
    """
    This logger is used to check some intermediate results.
    log(content) will log `content` for only one time.
    """
    def __init__(self, log_file, prefix='[OneTimeLogger]:', clear=False):
        self.record = defaultdict(bool)
        self.id_table = defaultdict(bool)
        self.log_file = log_file
        self.prefix = prefix

        if clear:
            with open(log_file, 'w') as f:
                f.close()
    def log(self, content: str):
        content = str(content)
        if content not in self.record:
            with open(self.log_file, 'a') as f:
                f.write(self.prefix + content + '\n')
                f.close()
            self.record[content] = True
    def log_id(self, content: str, id: int):
        content = str(content)
        if id not in self.id_table:
            with open(self.log_file, 'a') as f:
                f.write(self.prefix + content + '\n')
                f.close()
            self.id_table[id] = True