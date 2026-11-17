def test_overview_resources_match_published_objects_and_student_progress(client, student_headers):
    base = "/api/v1"
    course = "machine-learning"
    response = client.get(f"{base}/student/courses/{course}/overview", headers=student_headers)
    assert response.status_code == 200, response.text
    resources = response.json()["recent_resources"]
    graphs = client.get(f"{base}/student/courses/{course}/graph-resources", headers=student_headers).json()
    sets = client.get(f"{base}/student/courses/{course}/question-sets", headers=student_headers).json()["items"]
    videos = client.get(f"{base}/courses/{course}/resources?type=video", headers=student_headers).json()
    assert resources
    for resource in resources:
        if resource["resource_type"] == "knowledge_graph":
            assert resource["id"] in {g["id"] for g in graphs}
        elif resource["resource_type"] == "question_set":
            item = next(s for s in sets if s["id"] == resource["id"])
            assert resource["progress_completed"] == item["completed"]
            assert resource["progress_total"] == item["total"]
        else:
            assert resource["id"] in {v["id"] for v in videos}
    # Seeded descriptive video cards cannot create a nonexistent publication link.
    assert not videos
    assert all(resource["resource_type"] != "learning_video" for resource in resources)
