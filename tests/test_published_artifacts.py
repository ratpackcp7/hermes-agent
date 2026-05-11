"""Tests for agent/published_artifacts.py."""

import os
import tempfile
from pathlib import Path

import pytest

from agent.published_artifacts import (
    _SERVED_ROOT,
    _URL_BASE,
    _is_secret_path,
    _sanitize_filename,
    _collision_path,
    publish_artifact,
    ArtifactError,
)


class TestSanitizeFilename:
    def test_basic(self):
        assert _sanitize_filename("report.md") == "report.md"

    def test_path_separators_replaced(self):
        assert _sanitize_filename("../foo/bar.txt") == "foo_bar.txt"

    def test_leading_dots_stripped(self):
        assert _sanitize_filename(".hidden") == "hidden"

    def test_only_dots_becomes_default(self):
        assert _sanitize_filename("..") == "artifact"

    def test_empty_becomes_default(self):
        assert _sanitize_filename("") == "artifact"

    def test_preserves_extension(self):
        assert _sanitize_filename("data.json").endswith(".json")

    def test_whitespace_stripped(self):
        assert _sanitize_filename("  file.txt  ") == "file.txt"


class TestIsSecretPath:
    def test_dotenv_rejected(self):
        assert _is_secret_path("/path/to/.env")
        assert _is_secret_path(".env")

    def test_secret_containing_rejected(self):
        assert _is_secret_path("/path/with/secret.txt")

    def test_token_rejected(self):
        assert _is_secret_path("api_token.json")

    def test_credential_rejected(self):
        assert _is_secret_path("credentials.json")

    def test_key_rejected(self):
        assert _is_secret_path("my_api_key.txt")

    def test_password_rejected(self):
        assert _is_secret_path("passwords.txt")

    def test_id_rsa_rejected(self):
        assert _is_secret_path("id_rsa")

    def test_private_rejected(self):
        assert _is_secret_path("/etc/ssl/private/key.pem")

    def test_innocent_path_allowed(self):
        assert not _is_secret_path("/tmp/report.md")
        assert not _is_secret_path("/home/chris/projects/data.csv")
        assert not _is_secret_path("notes.txt")

    def test_key_in_middle_allowed(self):
        # "key" as a substring in the middle of a path that doesn't end with "key"
        assert not _is_secret_path("monkey_patch.py")
        assert not _is_secret_path("/home/chris/sticky_notes.md")


class TestCollisionPath:
    def test_no_collision(self, tmp_path):
        p = tmp_path / "unique.txt"
        result = _collision_path(p)
        assert result == p

    def test_collision_appends_hash(self, tmp_path):
        p = tmp_path / "report.md"
        p.write_text("original")
        result = _collision_path(p)
        assert result != p
        assert result.suffix == ".md"
        assert result.stem == "report_1"
        # Original file untouched
        assert p.read_text() == "original"

    def test_multiple_collisions(self, tmp_path):
        p = tmp_path / "data.json"
        p.write_text("first")
        c1 = _collision_path(p)
        c1.write_text("second")
        c2 = _collision_path(p)
        # Second collision should increment counter
        assert c2 == p.parent / "data_2.json"


class TestPublishArtifactIntegration:
    """Integration tests that create real files and publish them."""

    def create_source(self, content: str = "hello", suffix: str = ".txt") -> Path:
        src = Path(tempfile.mktemp(suffix=suffix))
        src.write_text(content)
        return src

    def test_publishes_file(self):
        src = self.create_source()
        try:
            url = publish_artifact(str(src))
            # URL should point to the right place
            assert url.startswith(f"{_URL_BASE}/bob/")
            # Published file should exist
            published = _SERVED_ROOT / "bob" / src.name
            assert published.exists() or any(
                (_SERVED_ROOT / "bob").glob(f"{src.stem}*{src.suffix}")
            )
            assert published.read_text() == "hello"
        finally:
            src.unlink(missing_ok=True)

    def test_returns_url_in_correct_format(self):
        src = self.create_source(suffix=".md")
        try:
            url = publish_artifact(str(src), display_name="result.md")
            assert url.startswith(f"{_URL_BASE}/bob/result")
            assert url.endswith(".md")
            # Verify the file is actually published
            published_dir = _SERVED_ROOT / "bob"
            assert list(published_dir.glob("result*"))
        finally:
            src.unlink(missing_ok=True)

    def test_custom_display_name(self):
        src = self.create_source()
        try:
            url = publish_artifact(str(src), display_name="custom-name.log")
            # Should be under the bob subdirectory with the display name (possibly with collision counter)
            assert "/bob/custom-name" in url
            assert url.endswith(".log")
        finally:
            src.unlink(missing_ok=True)

    def test_missing_source_rejected(self):
        with pytest.raises(ArtifactError, match="does not exist"):
            publish_artifact("/nonexistent/path.txt")

    def test_directory_rejected(self):
        with pytest.raises(ArtifactError, match="not a regular file"):
            publish_artifact(str(_SERVED_ROOT))

    def test_secret_source_rejected(self):
        # Create a file whose source PATH looks secret-like
        src = Path(tempfile.mktemp(suffix=".env"))
        src.write_text("KEY=value")
        try:
            # Call publish_artifact directly, expect ArtifactError
            with pytest.raises(ArtifactError, match="secret-like"):
                publish_artifact(str(src))
        finally:
            src.unlink(missing_ok=True)

    def test_secret_path_rejected(self):
        # Rejection is on the filename suffix (.env) matching the pattern
        assert _is_secret_path("/tmp/credentials.env")
        assert _is_secret_path(".env")
        assert not _is_secret_path("/tmp/notes.txt")

    def test_collision_does_not_overwrite(self):
        src = self.create_source(content="original")
        src2 = self.create_source(content="newer")
        try:
            url1 = publish_artifact(str(src), display_name="same.txt")
            url2 = publish_artifact(str(src2), display_name="same.txt")
            # Same filename should produce different URLs due to collision handling
            assert url1 != url2
            # Both published files should exist
            assert (_SERVED_ROOT / "bob" / "same.txt").exists()
            assert (_SERVED_ROOT / "bob" / "same_1.txt").exists()
        finally:
            src.unlink(missing_ok=True)
            src2.unlink(missing_ok=True)

    def test_secret_display_name_rejected(self):
        """publish_artifact should reject secret-like display names."""
        src = self.create_source()
        try:
            with pytest.raises(ArtifactError, match="rejected"):
                publish_artifact(str(src), display_name="secret_notes.txt")
        finally:
            src.unlink(missing_ok=True)

    def test_published_file_has_correct_permissions(self):
        """Published files must have mode 0644."""
        src = self.create_source()
        try:
            url = publish_artifact(str(src))
            # Extract the destination path from the URL
            rel_path = url.replace(f"{_URL_BASE}/", "")
            dest = _SERVED_ROOT / rel_path
            # Check file mode (last 4 bits of st_mode)
            import stat
            mode = stat.S_IMODE(dest.stat().st_mode)
            assert mode == 0o644, f"Expected 0644, got {oct(mode)}"
        finally:
            src.unlink(missing_ok=True)

    def test_artifact_directory_has_correct_permissions(self):
        """Artifact directory must have mode 0755."""
        import stat
        artifact_dir = _SERVED_ROOT / "bob"
        # Ensure directory exists (publish_artifact creates it, but let's trigger if not)
        if not artifact_dir.exists():
            publish_artifact(self.create_source())
        mode = stat.S_IMODE(artifact_dir.stat().st_mode)
        assert mode == 0o755, f"Expected 0755, got {oct(mode)}"

    @pytest.mark.parametrize(
        "secret_path",
        [
            ".env",
            "/path/to/.env",
            "my_secret.txt",
            "api_token.json",
            "credentials.yaml",
            "private_key.pem",
            "password.txt",
            "id_rsa",
            "id_rsa.pub",
            "/etc/ssl/private/key.pem",
        ],
    )
    def test_secret_sources_rejected_via_publish(self, secret_path):
        """Secret-like paths should raise ArtifactError when passed to publish_artifact."""
        import tempfile
        from pathlib import Path
        # Create a temp directory and exact secret filename to preserve pattern matching
        with tempfile.TemporaryDirectory() as tmpdir:
            # Use just the filename component of secret_path to avoid path issues
            filename = Path(secret_path).name
            src = Path(tmpdir) / filename
            src.write_text("secret")
            try:
                with pytest.raises(ArtifactError, match="secret-like"):
                    publish_artifact(str(src))
            finally:
                pass  # tmpdir auto-cleans

    def test_traversal_path_rejected(self):
        src = self.create_source()
        try:
            # display_name with traversal characters should raise ArtifactError
            with pytest.raises(ArtifactError, match="unsafe characters"):
                publish_artifact(str(src), display_name="../../etc/passwd")
        finally:
            src.unlink(missing_ok=True)


class TestSecretPathArguments:
    """Direct tests for specific secret patterns mentioned in the spec."""

    @pytest.mark.parametrize(
        "path",
        [
            ".env",
            "/path/to/.env",
            "my_secret.txt",
            "api_token.json",
            "credentials.yaml",
            "private_key.pem",
            "password.txt",
            "id_rsa",
            "id_rsa.pub",
            "/etc/ssl/private/key.pem",
        ],
    )
    def test_secret_paths(self, path):
        assert _is_secret_path(path), f"{path!r} should be rejected"

    @pytest.mark.parametrize(
        "path",
        [
            "report.md",
            "/tmp/data.csv",
            "notes.txt",
            "config.yaml",
            ".gitignore",
            "README.md",
        ],
    )
    def test_safe_paths(self, path):
        assert not _is_secret_path(path), f"{path!r} should be allowed"
