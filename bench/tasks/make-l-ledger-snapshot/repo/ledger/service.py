"""Application service: one command = load aggregate(s), run command, save."""
from .account import Account
from .errors import AccountExists


class LedgerService(object):
    def __init__(self, repository):
        self.repo = repository

    def open_account(self, account_id, owner):
        if self.repo.exists(account_id):
            raise AccountExists(account_id)
        account = Account(account_id)
        account.open(owner)
        self.repo.save(account)

    def deposit(self, account_id, value):
        account = self.repo.load(account_id)
        account.deposit(value)
        self.repo.save(account)

    def withdraw(self, account_id, value):
        account = self.repo.load(account_id)
        account.withdraw(value)
        self.repo.save(account)

    def place_hold(self, account_id, value, expires_at):
        account = self.repo.load(account_id)
        hold_id = account.place_hold(value, expires_at)
        self.repo.save(account)
        return hold_id

    def capture_hold(self, account_id, hold_id):
        account = self.repo.load(account_id)
        account.capture_hold(hold_id)
        self.repo.save(account)

    def release_hold(self, account_id, hold_id):
        account = self.repo.load(account_id)
        account.release_hold(hold_id)
        self.repo.save(account)

    def release_expired_holds(self, account_id, now):
        account = self.repo.load(account_id)
        released = account.release_expired(now)
        self.repo.save(account)
        return released

    def transfer(self, source_id, target_id, value, fee='0'):
        source = self.repo.load(source_id)
        target = self.repo.load(target_id)
        source.send_transfer(target_id, value, fee)
        target.receive_transfer(source_id, value)
        self.repo.save(source)
        self.repo.save(target)

    def balance(self, account_id):
        return self.repo.load(account_id).balance

    def available(self, account_id):
        return self.repo.load(account_id).available

    def account(self, account_id):
        return self.repo.load(account_id).describe()
