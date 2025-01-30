from pathlib import Path
from unittest.mock import patch, Mock, mock_open
import pytest
from django.contrib.auth.models import User
from ddpui.models.org import Org, OrgDbt
from ddpui.models.org_user import OrgUser
from ddpui.ddpdbt.elementary_service import (
    elementary_setup_status,
    get_elementary_target_schema,
    get_elementary_package_version,
    create_elementary_tracking_tables,
    extract_profile_from_generate_elementary_cli_profile,
    refresh_elementary_report_via_prefect,
)


pytestmark = pytest.mark.django_db


@pytest.fixture
def org_dbt():
    """org dbt"""
    return OrgDbt.objects.create(
        project_dir="test-project-dir",
        target_type="tgt_type",
        default_schema="test-default_schema",
    )


@pytest.fixture
def org(org_dbt):
    """org with dbt"""
    return Org.objects.create(slug="test-org", dbt=org_dbt)


@pytest.fixture
def authuser():
    """auth user"""
    return User.objects.create(email="fake-email", username="fake-username")


@pytest.fixture
def orguser(org, authuser):
    """org user"""
    return OrgUser.objects.create(org=org, user=authuser)


@patch("ddpui.ddpdbt.elementary_service.DbtProjectManager")
@patch("ddpui.ddpdbt.elementary_service.os.path.exists")
def test_elementary_setup_status(mock_os_path_exists, dbt_project_manager, org):
    """tests elementary_setup_status"""
    dbt_project_manager.get_dbt_project_dir = Mock(return_value="test-project-dir")
    mock_os_path_exists.return_value = True

    result = elementary_setup_status(org)
    assert result == {"status": "set-up"}

    dbt_project_manager.get_dbt_project_dir.assert_called_once_with(org.dbt)
    mock_os_path_exists.assert_called_once_with(Path("test-project-dir/elementary_profiles"))


def test_elementary_setup_status_no_dbt(org):
    """tests elementary_setup_status when dbt is not configured"""
    org.dbt = None
    result = elementary_setup_status(org)
    assert result == {"error": "dbt is not configured for this client"}


def test_get_elementary_target_schema_schema():
    """tests get_elementary_target_schema"""
    dbt_project_content = """
    models:
      elementary:
        schema: elementary
    """
    with patch("builtins.open", mock_open(read_data=dbt_project_content)):
        result = get_elementary_target_schema("dbt_project.yml")
        assert result == {"schema": "elementary"}


def test_get_elementary_target_schema_plus_schema():
    """tests get_elementary_target_schema"""
    dbt_project_content = """
    models:
      elementary:
        +schema: elementary
    """
    with patch("builtins.open", mock_open(read_data=dbt_project_content)):
        result = get_elementary_target_schema("dbt_project.yml")
        assert result == {"+schema": "elementary"}


def test_get_elementary_target_schema_no_elementary():
    """tests get_elementary_target_schema"""
    dbt_project_content = """
    models:
      not_elementary:
        schema: not_elementary
    """
    with patch("builtins.open", mock_open(read_data=dbt_project_content)):
        result = get_elementary_target_schema("dbt_project.yml")
        assert result is None


def test_get_elementary_target_schema_no_schema():
    """tests get_elementary_target_schema"""
    dbt_project_content = """
    models:
      elementary:
        other_key: other_value
    """
    with patch("builtins.open", mock_open(read_data=dbt_project_content)):
        result = get_elementary_target_schema("dbt_project.yml")
        assert result is None


def test_get_elementary_package_version_found():
    """tests get_elementary_package_version"""
    packages_content = """
    packages:
      - package: elementary-data/elementary
        version: 0.15.2
    """
    with patch("builtins.open", mock_open(read_data=packages_content)):
        result = get_elementary_package_version("packages.yml")
        assert result == {"package": "elementary-data/elementary", "version": "0.15.2"}


def test_get_elementary_package_version_not_found():
    """tests get_elementary_package_version"""
    packages_content = """
    packages:
      - package: other-package
        version: 1.0.0
    """
    with patch("builtins.open", mock_open(read_data=packages_content)):
        result = get_elementary_package_version("packages.yml")
        assert result is None


def test_get_elementary_package_version_no_packages_key():
    """tests get_elementary_package_version"""
    packages_content = """
    other_key:
      - package: elementary-data/elementary
        version: 0.15.2
    """
    with patch("builtins.open", mock_open(read_data=packages_content)):
        result = get_elementary_package_version("packages.yml")
        assert result is None


def test_get_elementary_package_version_empty_file():
    """tests get_elementary_package_version"""
    packages_content = ""
    with patch("builtins.open", mock_open(read_data=packages_content)):
        result = get_elementary_package_version("packages.yml")
        assert result is None


@patch("ddpui.ddpdbt.elementary_service.TaskProgress")
@patch("ddpui.ddpdbt.elementary_service.uuid4")
@patch("ddpui.ddpdbt.elementary_service.run_dbt_commands")
def test_create_elementary_tracking_tables(
    mock_run_dbt_commands, mock_uuid4, mock_task_progress, org
):
    """tests create_elementary_tracking_tables"""
    mock_task_progress.return_value = Mock(add=Mock())
    mock_uuid4.return_value = "test-uuid"
    mock_run_dbt_commands.delay = Mock()

    response = create_elementary_tracking_tables(org)
    assert response == {"task_id": "test-uuid"}

    mock_task_progress.assert_called_once_with("test-uuid", "run-dbt-commands-" + org.slug)
    mock_run_dbt_commands.delay.assert_called_once_with(
        org.id,
        "test-uuid",
        {
            # run parameters
            "options": {
                "select": "elementary",
            }
        },
    )


def test_extract_profile_from_generate_elementary_cli_profile_failure():
    """tests extract_profile_from_generate_elementary_cli_profile"""
    profile = """
bad_key:
  target: test-target
  schema: test-schema
  table: test-table
  columns: 
    - col1
    - col2
""".split(
        "\n"
    )

    error, _ = extract_profile_from_generate_elementary_cli_profile(profile)
    assert error == {"error": "macro elementary.generate_elementary_cli_profile returned nothing"}


def test_extract_profile_from_generate_elementary_cli_profile_success():
    """tests extract_profile_from_generate_elementary_cli_profile"""
    profile = """
elementary:
  target: test-target
  schema: test-schema
  table: test-table
  columns: 
    - col1
    - col2
""".split(
        "\n"
    )

    _, result = extract_profile_from_generate_elementary_cli_profile(profile)
    assert result == {
        "elementary": {
            "target": "test-target",
            "schema": "test-schema",
            "table": "test-table",
            "columns": ["col1", "col2"],
        }
    }


@patch("ddpui.ddpdbt.elementary_service.OrgDataFlowv1.objects.filter")
@patch("ddpui.ddpdbt.elementary_service.prefect_service.lock_tasks_for_deployment")
@patch("ddpui.ddpdbt.elementary_service.prefect_service.create_deployment_flow_run")
def test_refresh_elementary_report_via_prefect(
    mock_create_deployment_flow_run, mock_lock_tasks_for_deployment, mock_filter, orguser
):
    """tests refresh_elementary_report_via_prefect"""
    mock_odf = Mock(deployment_id="test-deployment-id")
    mock_filter.return_value = Mock(first=Mock(return_value=mock_odf))

    mock_lock_tasks_for_deployment.return_value = []
    mock_create_deployment_flow_run.return_value = "return-value"

    response = refresh_elementary_report_via_prefect(orguser)
    assert response == "return-value"

    mock_filter.assert_called_once_with(
        org=orguser.org, name__startswith=f"pipeline-{orguser.org.slug}-generate-edr"
    )

    mock_lock_tasks_for_deployment.assert_called_once_with("test-deployment-id", orguser)
    mock_create_deployment_flow_run.assert_called_once_with(mock_odf.deployment_id)
