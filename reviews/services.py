"""Reusable professor listing operations for HTTP views."""

def search_professors(
    repository, query="", *, school="", city="", department="", sort="rating", region=""
):
    """Return approved professor search results using the repository contract."""
    if region:
        return repository.search(query, school, city, department, sort, region=region)
    return repository.search(query, school, city, department, sort)


def professors_for_school(repository, school_slug):
    """Return the approved professors belonging to a school."""
    return search_professors(repository, "", school=school_slug)
