from pathlib import Path

ROOT = Path(__file__).parents[2]
LANDING_PAGE = ROOT / "docs" / "launch" / "index.html"
ROOT_REDIRECT = ROOT / "docs" / "index.html"
PAGES_WORKFLOW = ROOT / ".github" / "workflows" / "pages.yml"


def test_launch_page_has_product_hunt_ready_hero_and_ctas() -> None:
    html = LANDING_PAGE.read_text()

    assert "Swain - Ask your repo if it is safe to ship" in html
    assert "Ask your repo if it is safe to ship" in html
    assert "Download on GitHub" in html
    assert "curl -fsSL https://raw.githubusercontent.com" in html
    assert "../assets/demo/launch-card.png" in html
    assert "../assets/demo/scan-flow.gif" in html
    assert "review-only patch draft" in html


def test_launch_page_has_social_metadata_and_trust_links() -> None:
    html = LANDING_PAGE.read_text()
    social_image = (
        "https://descry-technologies.github.io/Swain/assets/demo/launch-card.png"
    )

    assert 'property="og:title"' in html
    assert social_image in html
    assert 'name="twitter:card" content="summary_large_image"' in html
    assert "Privacy and trust" in html
    assert "https://github.com/Descry-Technologies/Swain" in html


def test_launch_page_has_pages_root_and_deploy_workflow() -> None:
    redirect = ROOT_REDIRECT.read_text()
    workflow = PAGES_WORKFLOW.read_text()

    assert 'url=launch/' in redirect
    assert "actions/upload-pages-artifact" in workflow
    assert "actions/deploy-pages" in workflow
    assert "path: docs" in workflow
