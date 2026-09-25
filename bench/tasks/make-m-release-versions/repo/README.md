# fwver

Release tags for the device-fleet firmware updater. Rollout rules pick the
newest build a device may install with a constraint such as `^1.4.0`.

See `fwver/version.py` for the tag grammar. Run the tests with
`python3 -m unittest discover -s tests -v`.
