# The publish workflow's actions stay referenced by tag, not pinned to a commit SHA

publish.yml, whose PyPI jobs hold id-token: write, uses pypa/gh-action-pypi-publish@release/v1, actions/checkout@v4 and similar movable tags. Pinning to SHAs would harden the supply chain at the cost of update churn; the owner accepted the tags, which is PyPA's own documented usage (Round 47, package and publish path).
