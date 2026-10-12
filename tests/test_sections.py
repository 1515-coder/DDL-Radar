from mooc_deadlines.sections import extract_course_sections


class _Response:
    def __init__(self, payload, status=200) -> None:
        self.payload = payload
        self.status = status
        self.ok = status == 200

    def json(self):
        return self.payload


class _Requests:
    def get(self, url, params=None):
        if url.endswith("/activities"):
            return _Response(
                {
                    "activities": [
                        {"id": 1, "title": "第一章", "type": "page", "uploads": []}
                    ]
                }
            )
        collections = {
            "classroom-list": "classrooms",
            "interactions": "interactions",
            "group-sets": "group_sets",
            "notes": "notes",
            "correction-books": "correction_books",
            "topic-categories": "topic_categories",
        }
        endpoint = url.rsplit("/", 1)[-1]
        return _Response({collections[endpoint]: []})


class _Context:
    request = _Requests()


def test_all_course_sections_are_checked_and_empty_results_are_reported() -> None:
    report = []
    content = extract_course_sections(
        _Context(), [{"name": "电路", "zhiyuan_id": "34567"}], report
    )

    assert len(content) == 1
    assert content[0]["category"] == "章节"
    assert len(report) == 7
    assert sum(entry["items"] == 0 for entry in report) == 6
    assert all(entry["ok"] for entry in report)
