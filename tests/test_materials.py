from mooc_deadlines.materials import _items_from_payload, _load_catalog, _save_catalog


def test_material_catalog_round_trip(tmp_path) -> None:
    items = [
        {
            "course": "电路分析",
            "reference_id": "file-1",
            "name": "第一章.pdf",
            "url": "https://example.invalid/file-1",
        }
    ]

    _save_catalog(tmp_path, items)

    assert _load_catalog(tmp_path) == items


def test_origin_download_permission_is_accepted() -> None:
    payload = {
        "activities": [
            {
                "title": "第一章资料",
                "uploads": [
                    {
                        "reference_id": 5843,
                        "name": "讲义.pdf",
                        "allow_download": False,
                        "origin_allow_download": True,
                        "size": 123,
                        "source": "CHINAMCLOUD",
                    }
                ],
            }
        ]
    }

    items = _items_from_payload(
        payload, {"name": "电路分析", "zhiyuan_id": "20109"}, set()
    )

    assert len(items) == 1
    assert items[0]["reference_id"] == "5843"


def test_upload_without_either_download_permission_is_skipped() -> None:
    payload = {
        "activities": [
            {
                "uploads": [
                    {
                        "reference_id": 5843,
                        "allow_download": False,
                        "origin_allow_download": False,
                    }
                ]
            }
        ]
    }

    assert not _items_from_payload(payload, {"zhiyuan_id": "20109"}, set())
