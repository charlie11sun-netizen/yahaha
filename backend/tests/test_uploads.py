import zipfile
from io import BytesIO

from PIL import Image


def _auth(client):
    token = client.post(
        "/auth/register",
        json={"email": "u@u.com", "password": "secret1", "display_name": "U"},
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _png_bytes() -> bytes:
    out = BytesIO()
    Image.new("RGB", (2, 2), "red").save(out, format="PNG")
    return out.getvalue()


def _jpeg_with_exif() -> bytes:
    out = BytesIO()
    image = Image.new("RGB", (2, 2), "blue")
    exif = Image.Exif()
    exif[270] = "GPS-ish user description"
    image.save(out, format="JPEG", exif=exif)
    return out.getvalue()


def test_upload_ok(client):
    h = _auth(client)
    r = client.post("/uploads", files=[("files", ("a.png", _png_bytes(), "image/png"))], headers=h)
    assert r.status_code == 200
    assert r.json()["assets"][0]["name"] == "a.png"
    assert r.json()["assets"][0]["scan_status"] == "skipped"


def test_upload_bad_type(client):
    h = _auth(client)
    r = client.post("/uploads", files=[("files", ("a.exe", b"x", "application/x-msdownload"))], headers=h)
    assert r.status_code == 415


def test_upload_too_large(client):
    h = _auth(client)
    big = b"x" * (10 * 1024 * 1024 + 1)
    r = client.post("/uploads", files=[("files", ("big.png", big, "image/png"))], headers=h)
    assert r.status_code == 413


def test_upload_rejects_html_spoofed_as_image(client):
    h = _auth(client)
    r = client.post(
        "/uploads",
        files=[("files", ("x.png", b"<!doctype html><script>alert(1)</script>", "image/png"))],
        headers=h,
    )
    assert r.status_code == 415


def test_upload_rejects_svg_text_even_when_spoofed(client):
    h = _auth(client)
    r = client.post(
        "/uploads",
        files=[("files", ("x.png", b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', "image/png"))],
        headers=h,
    )
    assert r.status_code == 415


def test_upload_reencodes_jpeg_and_strips_exif(client, monkeypatch):
    from app.storage import s3

    h = _auth(client)
    captured = {}

    def _capture(key, body, content_type):
        captured["body"] = body
        captured["content_type"] = content_type
        return key

    monkeypatch.setattr(s3, "put_object", _capture)
    r = client.post(
        "/uploads",
        files=[("files", ("photo.jpg", _jpeg_with_exif(), "image/jpeg"))],
        headers=h,
    )
    assert r.status_code == 200
    assert captured["content_type"] == "image/jpeg"
    with Image.open(BytesIO(captured["body"])) as image:
        assert dict(image.getexif()) == {}


def test_upload_rejects_zip_bomb_ratio(client):
    h = _auth(client)
    data = BytesIO()
    with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("huge.txt", b"0" * (1024 * 1024))
    r = client.post(
        "/uploads",
        files=[("files", ("bomb.zip", data.getvalue(), "application/zip"))],
        headers=h,
    )
    assert r.status_code == 415


def test_upload_non_image_presign_forces_attachment(client, monkeypatch):
    from app.storage import s3

    h = _auth(client)
    dispositions = []

    def _url(key, **kwargs):
        dispositions.append(kwargs.get("response_content_disposition"))
        return f"https://oss.test/{key}"

    monkeypatch.setattr(s3, "presigned_url", _url)
    r = client.post(
        "/uploads",
        files=[("files", ("doc.pdf", b"%PDF-1.4\n%%EOF", "application/pdf"))],
        headers=h,
    )
    assert r.status_code == 200
    assert dispositions == ['attachment; filename="doc.pdf"']


def test_upload_rejects_too_many_files_before_storage(client, monkeypatch):
    from app.storage import s3

    h = _auth(client)
    writes = []
    monkeypatch.setattr(s3, "put_object", lambda *args: writes.append(args))
    files = [("files", (f"{i}.txt", b"x", "text/plain")) for i in range(7)]
    r = client.post("/uploads", files=files, headers=h)
    assert r.status_code == 413
    assert writes == []


def test_upload_strips_path_from_client_filename(client):
    h = _auth(client)
    r = client.post(
        "/uploads", files=[("files", ("../unsafe.txt", b"safe", "text/plain"))], headers=h
    )
    assert r.status_code == 200
    assert r.json()["assets"][0]["name"] == "unsafe.txt"
