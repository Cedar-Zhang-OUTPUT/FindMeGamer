from collections.abc import Iterable


SECURITY_CONCEPTS = (
    ("authorization",),
    ("auth", "header"),
    ("auth", "request", "header"),
    ("jwt",),
    ("jwt", "token"),
    ("passwd",),
    ("password",),
    ("pwd",),
    ("bearer",),
    ("cookie",),
    ("session", "credential"),
    ("session", "primary", "key"),
    ("secret",),
    ("credential",),
    ("token", "payload"),
    ("api", "key"),
    ("api", "primary", "key"),
    ("access", "key"),
    ("private", "key"),
    ("signing", "key"),
    ("encryption", "key"),
    ("auth", "key"),
)
RESTRICTED_CONTEXT_STEMS = (
    "match",
    "private",
    "internal",
    "hidden",
    "backend",
    "numeric",
)
RESTRICTED_METRICS = ("score", "rank", "order")
CONTEXT_METRIC_KEYS = (
    "score",
    "scores",
    "rank",
    "ranks",
    "order",
    "orders",
    "ordering",
)
NEAR_MISS_CONCEPTS = (
    ("secretary", "name"),
    ("tokenization", "method"),
    ("cookiecutter", "template"),
    ("accessibility", "keyboard", "layout"),
    ("privateering", "rank"),
    ("matchbox", "score"),
    ("backendless", "order"),
)


def key_forms(words: Iterable[str]) -> set[str]:
    singular = tuple(words)
    plural = (*singular[:-1], f"{singular[-1]}s")
    return {
        form
        for form_words in (singular, plural)
        for form in (
            "_".join(form_words),
            "-".join(form_words),
            " ".join(form_words),
            form_words[0] + "".join(word.title() for word in form_words[1:]),
            "".join(word.title() for word in form_words),
            "_".join(form_words).upper(),
            "".join(form_words),
        )
    }


SECURITY_KEY_FORMS = frozenset(
    form for concept in SECURITY_CONCEPTS for form in key_forms(concept)
)
NEAR_MISS_KEY_FORMS = frozenset(
    form for concept in NEAR_MISS_CONCEPTS for form in key_forms(concept)
)
RESTRICTED_ANCESTOR_FORMS = frozenset(
    form
    for context in RESTRICTED_CONTEXT_STEMS
    for form in key_forms((context, "result"))
)
RESTRICTED_COMPACT_METRIC_FORMS = frozenset(
    form
    for context in RESTRICTED_CONTEXT_STEMS
    for metric in RESTRICTED_METRICS
    for form in key_forms((context, metric))
)
