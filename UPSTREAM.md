# Upstream attribution

The `XiaomiCloudConnector` class in `app/upstream.py` is adapted from Piotr
Machowski's MIT-licensed Xiaomi Cloud Tokens Extractor. The user's downloaded
script was verified byte-for-byte against pinned upstream commit
`c4db715dace9806e905153c2977608873e8ab7c9` on 2026-11-26.
Exact source URL and SHA-256 are in `upstream-reference.json`.

Source: https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor

QR login and device enumeration in `app/cloud.py` adapt the same project's
protocol flow. This app replaces its CLI, password login, image server,
logging, and file outputs with isolated browser sessions. The upstream
copyright and license are retained in THIRD_PARTY_LICENSE.

This is an independent adaptation, not an official Xiaomi product or a
claim of endorsement by the upstream author.
