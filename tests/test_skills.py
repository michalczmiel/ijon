from ijon import (
    Skill,
    load_skills_from_directory,
    make_skill_tool,
)


def write_skill(root, name: str, content: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(content)


def test_missing_directory_returns_no_skills(tmp_path):
    assert load_skills_from_directory(str(tmp_path / "nope")) == []


def test_discovers_skills_and_skips_dirs_without_skill_md(tmp_path):
    write_skill(tmp_path, "alpha", "# Alpha\n\nbody")
    (tmp_path / "empty").mkdir()

    skills = load_skills_from_directory(str(tmp_path))

    assert [s.name for s in skills] == ["alpha"]
    assert skills[0].content == "# Alpha\n\nbody"


def test_discovers_multiple_skills_sorted_by_name(tmp_path):
    write_skill(tmp_path, "gamma", "# Gamma")
    write_skill(tmp_path, "alpha", "# Alpha")
    write_skill(tmp_path, "beta", "# Beta")

    skills = load_skills_from_directory(str(tmp_path))

    assert [s.name for s in skills] == ["alpha", "beta", "gamma"]


def test_metadata_falls_back_to_dir_name_and_first_heading():
    skill = Skill.from_text("# Secret Number\n\nrest", "secret-number")

    assert skill.name == "secret-number"
    assert skill.description == "Secret Number"


def test_metadata_reads_frontmatter():
    content = "---\nname: Cool Skill\ndescription: does cool things\n---\n# Heading"

    skill = Skill.from_text(content, "dir-name")

    assert skill.name == "Cool Skill"
    assert skill.description == "does cool things"


def test_metadata_frontmatter_name_only_falls_back_to_heading():
    content = "---\nname: Cool Skill\n---\n# Heading Desc\n\nbody"

    skill = Skill.from_text(content, "dir-name")

    assert skill.name == "Cool Skill"
    assert skill.description == "Heading Desc"


def test_skill_tool_exposes_names_as_enum():
    skills = [Skill(name="alpha", description="A", content="alpha body")]

    tool = make_skill_tool(skills)

    assert tool["name"] == "skill"
    assert tool["parameters"]["properties"]["name"]["enum"] == ["alpha"]


def test_skill_tool_loads_content():
    skills = [Skill(name="alpha", description="A", content="alpha body")]

    tool = make_skill_tool(skills)

    assert tool["execute"]({"name": "alpha"}) == "alpha body"


def test_skill_tool_reports_missing_name():
    tool = make_skill_tool([])

    assert "no skill name provided" in tool["execute"]({})


def test_skill_tool_reports_unknown_skill():
    tool = make_skill_tool([])

    assert "unknown skill" in tool["execute"]({"name": "ghost"})
