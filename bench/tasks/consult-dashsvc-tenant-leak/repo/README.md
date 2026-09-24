# dashsvc

Renders dashboard reports for three kinds of caller:

* numbered customer tenants (`X-Tenant: 42`),
* the internal operations account (`X-Tenant: system` plus a valid
  `X-Ops-Token`), which sees internal metrics,
* anonymous visitors of the public status page (no `X-Tenant` header), who
  only ever see public metrics.

Rendered reports are cached for a short TTL in a cache shared by all callers
and namespaced per tenant.

```
python3 -m unittest discover -s tests -v
```
