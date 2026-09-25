# docvault

A small multi-tenant document service.

* `models` - users, folders and documents; every object belongs to a workspace.
* `store` - in-memory persistence. The store performs **no** access checks.
* `acl` - the access rules (see the module docstring for listing vs reading).
* `service.DocumentService` - the API used by the HTTP layer; every public
  method takes the acting `User` and enforces `acl`.
* `audit` - an append-only log of reads and exports.

Run the tests with `python3 -m unittest discover -s tests -v`.
