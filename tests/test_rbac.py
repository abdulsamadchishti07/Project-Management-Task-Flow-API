from app import model
from app.rbac import Role


def create_workspace_helper(db_session, owner_id):
    ws = model.Workspace(name="Engineering Corp", owner_id=owner_id)
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)

    # Add owner membership
    owner_m = model.WorkspaceMember(user_id=owner_id, workspace_id=ws.id, role=Role.OWNER.value)
    db_session.add(owner_m)
    db_session.commit()
    return ws


def test_rbac_workspace_owner_access(client, auth_headers):
    # Owner creates workspace
    res = client.post("/workspace/", json={"name": "Owner Workspace"}, headers=auth_headers)
    assert res.status_code == 201
    ws_id = res.json()["id"]

    # Owner creates project
    proj_res = client.post(f"/project/workspace/{ws_id}", json={
        "name": "Backend Engine",
        "description": "FastAPI",
        "private": False
    }, headers=auth_headers)
    assert proj_res.status_code == 201


def test_rbac_viewer_cannot_create_task(client, db_session, test_user, test_viewer_user, viewer_headers):
    # 1. Setup workspace & project
    ws = create_workspace_helper(db_session, test_user.id)
    proj = model.Project(name="Core Project", workspace_id=ws.id, owner_id=test_user.id, private=False)
    db_session.add(proj)
    db_session.commit()

    # 2. Add Viewer user to workspace with VIEWER role
    viewer_member = model.WorkspaceMember(user_id=test_viewer_user.id, workspace_id=ws.id, role=Role.VIEWER.value)
    db_session.add(viewer_member)
    db_session.commit()

    # 3. Viewer CAN read tasks
    get_res = client.get(f"/tasks/project/{proj.id}", headers=viewer_headers)
    assert get_res.status_code == 200

    # 4. Viewer CANNOT create task -> 403 Forbidden!
    post_res = client.post(f"/tasks/project/{proj.id}", json={
        "title": "Unauthorized Task",
        "description": "Should fail",
        "priority": "high"
    }, headers=viewer_headers)
    assert post_res.status_code == 403
    assert "Insufficient permissions" in post_res.json()["detail"]


def test_rbac_member_can_create_task(client, db_session, test_user, test_member_user, member_headers):
    # 1. Setup workspace & project
    ws = create_workspace_helper(db_session, test_user.id)
    proj = model.Project(name="Core Project", workspace_id=ws.id, owner_id=test_user.id, private=False)
    db_session.add(proj)
    db_session.commit()

    # 2. Add Member user to workspace with MEMBER role
    member_rec = model.WorkspaceMember(user_id=test_member_user.id, workspace_id=ws.id, role=Role.MEMBER.value)
    db_session.add(member_rec)
    db_session.commit()

    # 3. Member CAN create task -> 201 Created!
    post_res = client.post(f"/tasks/project/{proj.id}", json={
        "title": "Member Task",
        "description": "Should succeed",
        "priority": "high"
    }, headers=member_headers)
    assert post_res.status_code == 201
    assert post_res.json()["title"] == "Member Task"


def test_rbac_viewer_cannot_comment(client, db_session, test_user, test_viewer_user, viewer_headers):
    ws = create_workspace_helper(db_session, test_user.id)
    proj = model.Project(name="Core Project", workspace_id=ws.id, owner_id=test_user.id, private=False)
    db_session.add(proj)
    db_session.commit()

    task = model.Tasks(project_id=proj.id, title="Test Task", priority="medium")
    db_session.add(task)
    db_session.commit()

    # Viewer member
    viewer_member = model.WorkspaceMember(user_id=test_viewer_user.id, workspace_id=ws.id, role=Role.VIEWER.value)
    db_session.add(viewer_member)
    db_session.commit()

    # Viewer CANNOT post comment -> 403 Forbidden!
    comm_res = client.post(f"/comments/task/{task.id}", json={
        "content": "Unauthorized comment"
    }, headers=viewer_headers)
    assert comm_res.status_code == 403


def test_rbac_non_member_access_denied(client, db_session, test_user, test_viewer_user, viewer_headers):
    # Workspace created by owner, viewer is NOT a member
    ws = create_workspace_helper(db_session, test_user.id)

    # Non-member tries to get workspace -> 403 Forbidden
    res = client.get(f"/workspace/{ws.id}", headers=viewer_headers)
    assert res.status_code == 403


def test_task_assignee_must_be_workspace_member(client, db_session, test_user, auth_headers):
    ws = create_workspace_helper(db_session, test_user.id)
    proj = model.Project(name="Proj", workspace_id=ws.id, owner_id=test_user.id, private=False)
    db_session.add(proj)
    db_session.commit()

    # User who is not in workspace
    outsider = model.Users(
        email="outsider@test.com",
        name="Outsider",
        password="password123",
        active=True
    )
    db_session.add(outsider)
    db_session.commit()

    # Try assigning outsider -> 400 Bad Request
    res_bad = client.post(f"/tasks/project/{proj.id}", json={
        "title": "Invalid Assignee Task",
        "assignee_id": outsider.id
    }, headers=auth_headers)
    assert res_bad.status_code == 400
    assert "Assignee must be a member" in res_bad.json()["detail"]

    # Assigning workspace owner -> 201 Created
    res_good = client.post(f"/tasks/project/{proj.id}", json={
        "title": "Valid Assignee Task",
        "assignee_id": test_user.id
    }, headers=auth_headers)
    assert res_good.status_code == 201


def test_cannot_invite_with_owner_role(client, db_session, test_user, auth_headers):
    ws = create_workspace_helper(db_session, test_user.id)

    res = client.post(f"/invitations/workspace/{ws.id}", json={
        "email": "invitee@test.com",
        "role": "owner"
    }, headers=auth_headers)
    # Either pydantic schema validation or router check rejects owner invite
    assert res.status_code in (400, 422)


def test_duplicate_pending_invitation_rejected(client, db_session, test_user, auth_headers):
    ws = create_workspace_helper(db_session, test_user.id)

    # First invite
    res1 = client.post(f"/invitations/workspace/{ws.id}", json={
        "email": "duplicate@test.com",
        "role": "member"
    }, headers=auth_headers)
    assert res1.status_code == 201

    # Second duplicate invite
    res2 = client.post(f"/invitations/workspace/{ws.id}", json={
        "email": "duplicate@test.com",
        "role": "member"
    }, headers=auth_headers)
    assert res2.status_code == 400
    assert "already pending" in res2.json()["detail"]


def test_soft_deleted_workspace_denied_in_rbac(client, db_session, test_user, auth_headers):
    ws = create_workspace_helper(db_session, test_user.id)
    ws.is_deleted = True
    db_session.commit()

    # Attempt to access or create project under deleted workspace -> 404
    res = client.get(f"/workspace/{ws.id}", headers=auth_headers)
    assert res.status_code == 404


def test_unregistered_project_invitee_acceptance_auto_enrolls_in_workspace(client, db_session, test_user, auth_headers):
    from app.oauth2 import create_access_token

    # 1. Workspace owner creates workspace and private project
    ws = create_workspace_helper(db_session, test_user.id)
    proj = model.Project(name="Secret Engine", workspace_id=ws.id, owner_id=test_user.id, private=True)
    db_session.add(proj)
    db_session.commit()

    # 2. Invite unregistered email to the project
    invite_res = client.post(f"/invitations/project/{proj.id}", json={
        "email": "unregistered@test.com",
        "role": "member"
    }, headers=auth_headers)
    assert invite_res.status_code == 201
    invite_id = invite_res.json()["id"]

    # 3. User registers and activates account
    new_user = model.Users(
        email="unregistered@test.com",
        name="New Colleague",
        password="securepassword123",
        active=True,
        token_version=1
    )
    db_session.add(new_user)
    db_session.commit()
    db_session.refresh(new_user)

    new_user_token = create_access_token({"sub": str(new_user.id), "ver": 1})
    new_user_headers = {"Authorization": f"Bearer {new_user_token}"}

    # 4. New user accepts the project invitation
    accept_res = client.post(f"/invitations/project/{invite_id}/accept", headers=new_user_headers)
    assert accept_res.status_code == 200

    # 5. Verify auto-enrollment: user is now a workspace member AND project member
    ws_membership = db_session.query(model.WorkspaceMember).filter(
        model.WorkspaceMember.workspace_id == ws.id,
        model.WorkspaceMember.user_id == new_user.id
    ).first()
    assert ws_membership is not None
    assert ws_membership.role == Role.MEMBER.value

    proj_membership = db_session.query(model.ProjectMember).filter(
        model.ProjectMember.project_id == proj.id,
        model.ProjectMember.user_id == new_user.id
    ).first()
    assert proj_membership is not None
    assert proj_membership.role == "member"

    # 6. Verify user can now access project tasks
    tasks_res = client.get(f"/tasks/project/{proj.id}", headers=new_user_headers)
    assert tasks_res.status_code == 200


def test_project_admin_can_invite_to_project(client, db_session, test_user, test_member_user, member_headers):
    # Setup workspace and project
    ws = create_workspace_helper(db_session, test_user.id)
    proj = model.Project(name="Core Project", workspace_id=ws.id, owner_id=test_user.id, private=True)
    db_session.add(proj)
    db_session.commit()

    # Member user has role MEMBER in workspace, but role ADMIN in project
    ws_member = model.WorkspaceMember(user_id=test_member_user.id, workspace_id=ws.id, role=Role.MEMBER.value)
    proj_admin = model.ProjectMember(user_id=test_member_user.id, project_id=proj.id, role=Role.ADMIN.value)
    db_session.add(ws_member)
    db_session.add(proj_admin)
    db_session.commit()

    # Project admin invites a new member -> 201 Created via Dual Authorization!
    invite_res = client.post(f"/invitations/project/{proj.id}", json={
        "email": "teammate@test.com",
        "role": "member"
    }, headers=member_headers)
    assert invite_res.status_code == 201


def test_cannot_accept_invite_to_deleted_workspace(client, db_session, test_user, test_member_user, member_headers, auth_headers):
    ws = create_workspace_helper(db_session, test_user.id)

    # Send invitation
    invite_res = client.post(f"/invitations/workspace/{ws.id}", json={
        "email": test_member_user.email,
        "role": "member"
    }, headers=auth_headers)
    assert invite_res.status_code == 201
    invite_id = invite_res.json()["id"]

    # Delete workspace
    ws.is_deleted = True
    db_session.commit()

    # Attempt to accept invitation -> 400 Bad Request
    accept_res = client.post(f"/invitations/workspace/{invite_id}/accept", headers=member_headers)
    assert accept_res.status_code == 400
    assert "deleted or does not exist" in accept_res.json()["detail"]


def test_invalid_task_status_or_priority_returns_422(client, db_session, test_user, auth_headers):
    ws = create_workspace_helper(db_session, test_user.id)
    proj = model.Project(name="Core Project", workspace_id=ws.id, owner_id=test_user.id, private=False)
    db_session.add(proj)
    db_session.commit()

    # Invalid status enum
    res_status = client.get(f"/tasks/project/{proj.id}?status=invalid_status", headers=auth_headers)
    assert res_status.status_code == 422

    # Invalid priority enum
    res_prio = client.get(f"/tasks/project/{proj.id}?priority=invalid_priority", headers=auth_headers)
    assert res_prio.status_code == 422


def test_readiness_probe(client):
    res = client.get("/ready")
    assert res.status_code == 200
    assert res.json() == {"status": "ready"}


def test_user_soft_deactivation_preserves_workspace_and_audit(client, db_session, test_user, auth_headers):
    ws = create_workspace_helper(db_session, test_user.id)

    # Soft deactivate user account
    delete_res = client.delete(f"/user/{test_user.id}", headers=auth_headers)
    assert delete_res.status_code == 204

    # Verify user is deactivated
    db_session.refresh(test_user)
    assert test_user.active is False

    # Verify workspace still exists in database
    existing_ws = db_session.query(model.Workspace).filter(model.Workspace.id == ws.id).first()
    assert existing_ws is not None
    assert existing_ws.owner_id == test_user.id


def test_user_profile_update_without_password(client, db_session, test_user, auth_headers):
    original_password_hash = test_user.password

    update_res = client.put(f"/user/{test_user.id}", json={
        "name": "Updated Real Name"
    }, headers=auth_headers)
    assert update_res.status_code == 200
    assert update_res.json()["name"] == "Updated Real Name"

    # Password hash is unmodified
    db_session.refresh(test_user)
    assert test_user.password == original_password_hash


def test_invitation_cannot_be_accepted_twice(client, db_session, test_user, test_member_user, member_headers, auth_headers):
    ws = create_workspace_helper(db_session, test_user.id)

    # Send invitation
    invite_res = client.post(f"/invitations/workspace/{ws.id}", json={
        "email": test_member_user.email,
        "role": "member"
    }, headers=auth_headers)
    assert invite_res.status_code == 201
    invite_id = invite_res.json()["id"]

    # First acceptance succeeds
    accept_res1 = client.post(f"/invitations/workspace/{invite_id}/accept", headers=member_headers)
    assert accept_res1.status_code == 200

    # Second acceptance fails (already accepted, status is no longer pending)
    accept_res2 = client.post(f"/invitations/workspace/{invite_id}/accept", headers=member_headers)
    assert accept_res2.status_code in (404, 409)



