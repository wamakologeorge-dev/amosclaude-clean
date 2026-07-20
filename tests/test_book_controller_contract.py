from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_book_controller_has_validation_and_safe_status_codes() -> None:
    source = (ROOT / "controllers" / "book.controller.js").read_text(encoding="utf-8")
    assert "validateBookPayload" in source
    assert "book_service_error" in source
    assert "res.status(201)" in source
    assert "res.status(204)" in source
    assert "error.stack" not in source


def test_book_route_is_router_not_duplicate_controller() -> None:
    source = (ROOT / "routes" / "book.route.js").read_text(encoding="utf-8")
    assert "express.Router()" in source
    assert "controllers/book.controller" in source
    assert "class BookController" not in source
    for method in ("router.get", "router.post", "router.patch", "router.delete"):
        assert method in source


def test_book_service_has_a_real_model_backend() -> None:
    service = (ROOT / "services" / "book.service.js").read_text(encoding="utf-8")
    model_path = ROOT / "models" / "book.model.js"
    model = model_path.read_text(encoding="utf-8")
    assert "../models/book.model" in service
    assert model_path.is_file()
    assert "AMOSCLAUD_BOOK_STORE" in model
    assert "crypto.randomUUID" in model
    assert "fs.rename" in model
