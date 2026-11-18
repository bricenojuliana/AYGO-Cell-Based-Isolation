"""Architecture rules on the SAM templates, so they cannot silently regress (reused idea from Campus Café)."""
from pathlib import Path

import pytest
import yaml

from cellsaas.router.handler import ROUTES

ROOT = Path(__file__).resolve().parents[2]


class CfnLoader(yaml.SafeLoader):
    pass


def _tag(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return {suffix: loader.construct_scalar(node)}
    if isinstance(node, yaml.SequenceNode):
        return {suffix: loader.construct_sequence(node, deep=True)}
    return {suffix: loader.construct_mapping(node, deep=True)}


CfnLoader.add_multi_constructor("!", _tag)


def _load(name):
    return yaml.load((ROOT / "templates" / name).read_text(), Loader=CfnLoader)


@pytest.fixture(scope="module", params=["cell.yaml", "platform.yaml", "control.yaml"])
def template(request):
    return _load(request.param)


def test_adr008_roles_are_only_created_when_no_execution_role_is_given(template):
    roles = {k: v for k, v in template["Resources"].items() if v["Type"] == "AWS::IAM::Role"}
    assert roles, "the least-privilege role for normal accounts must exist"
    assert all(role.get("Condition") == "CreateRole" for role in roles.values())
    for fn in (v for v in template["Resources"].values() if v["Type"] == "AWS::Serverless::Function"):
        assert fn["Properties"]["Role"] == {"If": ["CreateRole", {"GetAtt": next(iter(roles)) + ".Arn"},
                                                     {"Ref": "ExecutionRoleArn"}]}


def test_adr004_cell_table_is_provisioned_and_tenant_partitioned():
    table = _load("cell.yaml")["Resources"]["OrdersTable"]["Properties"]
    assert table["BillingMode"] == "PROVISIONED"
    assert table["KeySchema"][0] == {"AttributeName": "pk", "KeyType": "HASH"}


def test_adr003_router_reaches_cells_by_name_prefix():
    cell_fn = _load("cell.yaml")["Resources"]["CellFunction"]["Properties"]
    router_env = _load("platform.yaml")["Resources"]["RouterFunction"]["Properties"]["Environment"]["Variables"]
    assert cell_fn["FunctionName"] == {"Sub": "cellsaas-cell-${CellId}"}
    assert router_env["CELL_FUNCTION_PREFIX"] == "cellsaas-cell-"


def test_api_routes_match_router_routes():
    events = _load("platform.yaml")["Resources"]["RouterFunction"]["Properties"]["Events"].values()
    declared = {f'{e["Properties"]["Method"]} {e["Properties"]["Path"]}' for e in events}
    assert declared == set(ROUTES)


def test_least_privilege_cell_role_touches_only_its_own_resources():
    policies = _load("cell.yaml")["Resources"]["CellRole"]["Properties"]["Policies"]
    actions = {a for p in policies for s in p["PolicyDocument"]["Statement"]
               for a in (s["Action"] if isinstance(s["Action"], list) else [s["Action"]])}
    assert actions == {"dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query", "ssm:GetParameter",
                       "logs:CreateLogStream", "logs:PutLogEvents"}
