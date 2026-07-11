from project_semantics_hygiene import RouteNormalizer, canonical_route_key


def test_fastapi_brace_params():
    r = RouteNormalizer().normalize("/api/users/{user_id}", "get")
    assert r.method == "GET"
    assert r.canonical_path == "/api/users/{param}"
    assert r.param_names == ["user_id"]


def test_express_colon_params():
    r = RouteNormalizer().normalize("/api/users/:id", "POST")
    assert r.method == "POST"
    assert r.canonical_path == "/api/users/{param}"
    assert r.param_names == ["id"]


def test_angle_params():
    r = RouteNormalizer().normalize("/api/users/<id>")
    assert r.canonical_path == "/api/users/{param}"
    assert r.param_names == ["id"]


def test_template_strings():
    r = RouteNormalizer().normalize("`/api/users/${id}`")
    assert r.canonical_path == "/api/users/{param}"
    assert r.param_names == ["id"]
    assert r.confidence >= 0.85


def test_concatenated_paths():
    rn = RouteNormalizer()
    assert rn.normalize('"/api/users/" + id').canonical_path == "/api/users/{param}"
    r = rn.normalize('"/api/users/" + encodeURIComponent(id)')
    assert r.canonical_path == "/api/users/{param}"
    assert r.param_names == ["id"]
    assert r.confidence == 0.65


def test_query_trailing_duplicate_slash_normalization():
    r = RouteNormalizer().normalize("//api/users/{id}/?expand=true")
    assert r.canonical_path == "/api/users/{param}"


def test_equivalent_frontend_backend_dynamic_paths():
    rn = RouteNormalizer()
    assert rn.equivalent("/api/admin/accounts/${id}", "/api/admin/accounts/{account_id}")
    a = rn.normalize("/api/orbit/accounts/${accountId}/renew", "post")
    b = rn.normalize("/api/orbit/accounts/{account_id}/renew", "POST")
    assert a.canonical_path == b.canonical_path
    assert canonical_route_key(a.method, a.canonical_path) == canonical_route_key(b.method, b.canonical_path)


def test_method_aware_route_equivalence():
    rn = RouteNormalizer()
    assert rn.equivalent("/api/users/${id}", "/api/users/{user_id}", "get", "GET")
    assert not rn.equivalent("/api/users/${id}", "/api/users/{user_id}", "POST", "GET")
    assert rn.equivalent_strict("/api/users/${id}", "/api/users/{user_id}", "GET", "GET")
    assert not rn.equivalent_strict("/api/users/${id}", "/api/users/{user_id}", "POST", "GET")


def test_non_equivalent_similar_paths():
    rn = RouteNormalizer()
    assert not rn.equivalent("/api/admin/accounting/{id}", "/api/admin/accounts/{id}")


def test_method_case_normalization():
    r = RouteNormalizer().normalize("/x", "patch")
    assert r.method == "PATCH"
