from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm

from Api_mock.auth import (
    login, get_current_user, create_token, require_role,
    registration_new_user, create_agent_token, get_current_agent,
)
from Api_mock.audit import record_activity, record_activity_to_db
from Api_mock.Basemodel import CustomerCreate, CustomerResponse,UserResponse, UserCreate
from typing import List
import Api_mock.Basemodel
import sqlite3
from fastapi import Depends, HTTPException, status

DB_PATH = "Sqllite/insurance.db"

app = FastAPI(title="Insurance Mock API")


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _record_activity(
    *,
    event_type: str,
    outcome: str,
    actor_user_id=None,
    resource_type=None,
    resource_id=None,
    status_code=None,
):
    record_activity_to_db(
        DB_PATH,
        event_type=event_type,
        outcome=outcome,
        actor_user_id=actor_user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        status_code=status_code,
    )


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.post("/login")
def login_route(form_data: OAuth2PasswordRequestForm = Depends()):
    return login(form_data)


@app.get("/auth/me")
def me(current_user: dict = Depends(get_current_user)):
    conn = _get_conn()
    try:
        row = conn.execute(
            """SELECT user_id, email, name, role, is_active, last_login, created_at
               FROM users WHERE user_id = ?""",
            (current_user["user_id"],),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    return dict(row)


@app.post("/auth/token")
def generate_token(user=Depends(get_current_user)):
    token = create_token(user["user_id"], user["role"])
    return {"access_token": token, "token_type": "bearer"}


# ── Customers ─────────────────────────────────────────────────────────────────


# GET all customers — Admin and Agent only
# @app.get("/customers", response_model=List[CustomerResponse])
# def get_all_customers(_=Depends(require_role("Admin", "Agent"))):
#     conn = _get_conn()
#     try:
#         rows = conn.execute("SELECT * FROM customers").fetchall()
#         return [dict(r) for r in rows]
#     finally:
#         conn.close()




# GET one customer by ID
# Admin/Agent can view anyone, Customer can only view their own
@app.get("/customers/{customer_id}", response_model=CustomerResponse)
def get_customer_profiles(
    customer_id: int,
    user=Depends(get_current_user)):
    conn = _get_conn()

    try:
        # Customer: Can only access their own profile
        if user["role"] == "Customer":

            row = conn.execute(
                """
                SELECT *
                FROM customers
                WHERE customer_id = ?
                  AND user_id = ?
                """,
                (customer_id, user["user_id"])
            ).fetchone()

        # Admin: Can access any customer
        elif user["role"] == "Admin":

            row = conn.execute(
                """
                SELECT *
                FROM customers
                WHERE customer_id = ?
                """,
                (customer_id,)
            ).fetchone()

        # Agent: Can only access customers with policies
        # assigned to the logged-in agent
        elif user["role"] == "Agent":

            row = conn.execute(
                """
                SELECT c.*
                FROM customers c
                INNER JOIN policies p
                    ON p.customer_id = c.customer_id
                INNER JOIN agents a
                    ON a.agent_id = p.agent_id
                WHERE c.customer_id = ?
                  AND a.user_id = ?
                LIMIT 1
                """,
                (customer_id, user["user_id"])
            ).fetchone()

        else:
            record_activity(
                conn,
                event_type="CUSTOMER_READ",
                outcome="DENIED",
                actor_user_id=user["user_id"],
                resource_type="CUSTOMER",
                resource_id=customer_id,
                status_code=403,
            )
            conn.commit()
            raise HTTPException(
                status_code=403,
                detail="Access denied"
            )

        if row is None:
            record_activity(
                conn,
                event_type="CUSTOMER_READ",
                outcome="DENIED",
                actor_user_id=user["user_id"],
                resource_type="CUSTOMER",
                resource_id=customer_id,
                status_code=404,
            )
            conn.commit()
            raise HTTPException(
                status_code=404,
                detail="Customer not found or access denied"
            )

        record_activity(
            conn,
            event_type="CUSTOMER_READ",
            outcome="SUCCESS",
            actor_user_id=user["user_id"],
            resource_type="CUSTOMER",
            resource_id=customer_id,
            status_code=200,
        )
        conn.commit()
        return dict(row)

    finally:
        conn.close()


# CREATE customer profile — Admin or the authenticated Customer
@app.post("/customers", response_model=CustomerResponse, status_code=201)
def create_customer(data: CustomerCreate, user=Depends(get_current_user)):
    if user["role"] not in ("Admin", "Customer"):
        _record_activity(
            event_type="CUSTOMER_CREATE",
            outcome="DENIED",
            actor_user_id=user["user_id"],
            resource_type="CUSTOMER",
            status_code=403,
        )
        raise HTTPException(status_code=403, detail="Access denied")

    conn = _get_conn()
    try:
        profile_user_id = data.user_id
        if user["role"] == "Customer":
            account = conn.execute(
                "SELECT email FROM users WHERE user_id = ?",
                (user["user_id"],),
            ).fetchone()
            if account is None:
                raise HTTPException(status_code=401, detail="User account not found")
            if data.email.casefold() != account["email"].casefold():
                raise HTTPException(
                    status_code=400,
                    detail="Customer profile email must match the registered account",
                )
            profile_user_id = user["user_id"]

        if profile_user_id is not None:
            linked_user = conn.execute(
                "SELECT email, role FROM users WHERE user_id = ?",
                (profile_user_id,),
            ).fetchone()
            if linked_user is None or linked_user["role"] != "Customer":
                raise HTTPException(
                    status_code=400,
                    detail="user_id must belong to a registered customer",
                )
            if linked_user["email"].casefold() != data.email.casefold():
                raise HTTPException(
                    status_code=400,
                    detail="Customer profile email must match the registered account",
                )
            existing_profile = conn.execute(
                "SELECT customer_id FROM customers WHERE user_id = ?",
                (profile_user_id,),
            ).fetchone()
            if existing_profile:
                raise HTTPException(
                    status_code=409,
                    detail="A profile already exists for this user",
                )

        duplicate = conn.execute(
            """SELECT email, pan_number, aadhar_number
               FROM customers
               WHERE email = ?
                        OR (? IS NOT NULL AND pan_number = ?)
                        OR (? IS NOT NULL AND aadhar_number = ?)
               LIMIT 1""",
            (data.email, data.pan_number, data.pan_number,
             data.aadhar_number, data.aadhar_number),
        ).fetchone()
        if duplicate:
            if duplicate["email"] == data.email:
                duplicate_field = "email"
            elif data.pan_number and duplicate["pan_number"] == data.pan_number:
                duplicate_field = "PAN"
            else:
                duplicate_field = "Aadhaar"
            raise HTTPException(
                status_code=409,
                detail=f"A customer with this {duplicate_field} already exists",
            )
        cursor = conn.execute(
            """INSERT INTO customers
               (user_id, first_name, last_name, dob, gender, email,
                phone, address, city, state, pincode, pan_number, aadhar_number)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
               (profile_user_id, data.first_name, data.last_name, str(data.dob),
             data.gender.title() if data.gender else None, data.email, data.phone, data.address,
             data.city, data.state, data.pincode, data.pan_number, data.aadhar_number)
        )
        record_activity(
            conn,
            event_type="CUSTOMER_CREATE",
            outcome="SUCCESS",
            actor_user_id=user["user_id"],
            resource_type="CUSTOMER",
            resource_id=cursor.lastrowid,
            status_code=201,
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM customers WHERE customer_id=?", (cursor.lastrowid,)
        ).fetchone()
        return dict(row)
    except sqlite3.IntegrityError as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise HTTPException(
                status_code=409,
                detail="A customer with this email, PAN, or Aadhaar already exists",
            ) from exc
        raise
    finally:
        conn.close()


# Admins can update any profile; customers can update their own profile.
@app.put("/customers/{customer_id}", response_model=CustomerResponse)
def update_customer(customer_id: int, data: CustomerCreate, user=Depends(get_current_user)):
    if user["role"] not in ("Admin", "Customer"):
        _record_activity(
            event_type="CUSTOMER_UPDATE",
            outcome="DENIED",
            actor_user_id=user["user_id"],
            resource_type="CUSTOMER",
            resource_id=customer_id,
            status_code=403,
        )
        raise HTTPException(status_code=403, detail="Access denied")

    conn = _get_conn()
    try:
        query = """UPDATE customers SET
               first_name=?, last_name=?, dob=?, gender=?, email=?,
               phone=?, address=?, city=?, state=?, pincode=?,
               pan_number=?, aadhar_number=?
               WHERE customer_id=?"""
        values = (
            data.first_name, data.last_name, str(data.dob), data.gender,
            data.email, data.phone, data.address, data.city, data.state,
            data.pincode, data.pan_number, data.aadhar_number, customer_id,
        )
        if user["role"] == "Customer":
            query += " AND user_id=?"
            values += (user["user_id"],)

        conn.execute(query, values)
        row = conn.execute(
            "SELECT * FROM customers WHERE customer_id=?", (customer_id,)
        ).fetchone()
        if row is None:
            record_activity(
                conn,
                event_type="CUSTOMER_UPDATE",
                outcome="DENIED",
                actor_user_id=user["user_id"],
                resource_type="CUSTOMER",
                resource_id=customer_id,
                status_code=404,
            )
            conn.commit()
            raise HTTPException(status_code=404, detail="Customer not found")
        record_activity(
            conn,
            event_type="CUSTOMER_UPDATE",
            outcome="SUCCESS",
            actor_user_id=user["user_id"],
            resource_type="CUSTOMER",
            resource_id=customer_id,
            status_code=200,
        )
        conn.commit()
    finally:
        conn.close()
    return dict(row)


# DELETE customer — Admin only
@app.delete("/customers/{customer_id}", status_code=204)
def delete_customer(customer_id: int, user=Depends(require_role("Admin"))):
    conn = _get_conn()
    try:
        affected = conn.execute(
            "DELETE FROM customers WHERE customer_id=?", (customer_id,)
        ).rowcount
        if affected == 0:
            record_activity(
                conn,
                event_type="CUSTOMER_DELETE",
                outcome="DENIED",
                actor_user_id=user["user_id"],
                resource_type="CUSTOMER",
                resource_id=customer_id,
                status_code=404,
            )
            conn.commit()
        else:
            record_activity(
                conn,
                event_type="CUSTOMER_DELETE",
                outcome="SUCCESS",
                actor_user_id=user["user_id"],
                resource_type="CUSTOMER",
                resource_id=customer_id,
                status_code=204,
            )
            conn.commit()
    finally:
        conn.close()
    if affected == 0:
        raise HTTPException(status_code=404, detail="Customer not found")



@app.post("/registration", response_model=UserResponse, status_code=201)
def registration_customer(registration: UserCreate):
    result = registration_new_user(registration.dict())
    return UserResponse(**result)


@app.post("/agents/customers", response_model=UserResponse, status_code=201)
@app.post("/registaion", response_model=UserResponse, status_code=201)
def registration_customer_by_agent(
    registration: UserCreate,
    user=Depends(require_role("Agent")),
):
    result = registration_new_user(
        registration.dict(), actor_user_id=user["user_id"]
    )
    return UserResponse(**result)
    

            
         
 #============== brach craetion +=============
@app.post(
    "/branch",
    response_model=Api_mock.Basemodel.BranchResponse,
    status_code=201
)
def create_branch(
    data: Api_mock.Basemodel.BranchCreate,
    user=Depends(require_role("Admin"))
):
    conn = _get_conn()
    cursor = conn.cursor()

    try:
        # Check whether branch already exists
        existing_branch = cursor.execute(
            """
            SELECT * FROM branches
            WHERE branch_name = ?
            """,
            (data.branch_name,)
        ).fetchone()

        if existing_branch:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Branch already exists"
            )

        # Insert new branch
        cursor.execute(
            """
            INSERT INTO branches
            (branch_name, region, address, contact_phone, contact_email)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                data.branch_name,
                data.region,
                data.address,
                data.contact_phone,
                data.contact_email
            )
        )

        branch_id = cursor.lastrowid

        record_activity(
            conn,
            event_type="BRANCH_CREATE",
            outcome="SUCCESS",
            actor_user_id=user["user_id"],
            resource_type="BRANCH",
            resource_id=branch_id,
            status_code=201,
        )
        conn.commit()

        # Get newly created branch
        row = cursor.execute(
            "SELECT * FROM branches WHERE branch_id = ?",
            (branch_id,)
        ).fetchone()

        return Api_mock.Basemodel.BranchResponse(**dict(row))

    finally:
        conn.close()


    # finally:
       
    #     conn.close()    

# 422 -> Validation Error
# @app.put("/branchupdate/{branch_id}", response_model=Api_mock.Basemodel.BranchResponse)
# def update_branch(branch_id , data:Api_mock.Basemodel.BranchCreate, user=Depends(require_role("Admin"))):
#     conn=_get_conn()
#     cursor=conn.cursor()
#     try:
#         cursor.execute('''
#         UPDATE branches
#         SET
#             branch_name = ?,
#             region = ?,
#             address = ?,
#             contact_phone = ?,
#             contact_email = ?
#         WHERE branch_id = ?
#         ''', (data.branch_name, data.region, data.address, data.contact_phone, 
#               data.contact_email, branch_id))
#         # update_last_details=cursor.lastrowid 
#         # if(update_last_details==None):  
#         #     raise HTTPException(
#         #                     status_code=status.HTTP_422_INTERNAL_SERVER_ERROR  ,
#         #                     detail="Brach data is not successed"
            

#         #      
#         # 
#         #            )  

#         print("Received branch_id:", branch_id)
#         # if cursor.rowcount == 0:
#         #     raise HTTPException(
#         #     status_code=404,
#         #     detail="Branch not found"
#         # )
    
#         conn.commit()
#         all_rows = cursor.execute(
#             "SELECT branch_id, branch_name FROM branches"
#         ).fetchall()

#         print("All branches:", all_rows)

#         print("Received branch_id:", branch_id)

#         row=cursor.execute("SELECT * FROM branches WHERE branch_id=?", (branch_id,)).fetchone()  
                
#         return Api_mock.Basemodel.BranchResponse(**dict(row))

#     finally:
#         conn.close()     
@app.patch("/branchupdate/{branch_id}",
           response_model=Api_mock.Basemodel.BranchResponse)
def update_branch(
    branch_id: int,
    data: Api_mock.Basemodel.BranchUpdate,
    user=Depends(require_role("Admin"))
):
    conn = _get_conn()
    cursor = conn.cursor()

    try:
        # Get only fields sent by the user
        update_data = data.model_dump(exclude_unset=True)

        if not update_data:
            raise HTTPException(
                status_code=400,
                detail="No fields provided for update"
            )

        # Check whether branch exists
        row = cursor.execute(
            "SELECT * FROM branches WHERE branch_id=?",
            (branch_id,)
        ).fetchone()

        if row is None:
            record_activity(
                conn,
                event_type="BRANCH_UPDATE",
                outcome="DENIED",
                actor_user_id=user["user_id"],
                resource_type="BRANCH",
                resource_id=branch_id,
                status_code=404,
            )
            conn.commit()
            raise HTTPException(
                status_code=404,
                detail="Branch not found"
            )

        # Dynamically construct UPDATE query
        columns = ", ".join(
            f"{column} = ?" for column in update_data.keys()
        )

        values = list(update_data.values())
        values.append(branch_id)

        cursor.execute(
            f"""
            UPDATE branches
            SET {columns}
            WHERE branch_id = ?
            """,
            values
        )

        record_activity(
            conn,
            event_type="BRANCH_UPDATE",
            outcome="SUCCESS",
            actor_user_id=user["user_id"],
            resource_type="BRANCH",
            resource_id=branch_id,
            status_code=200,
        )
        conn.commit()

        updated_row = cursor.execute(
            "SELECT * FROM branches WHERE branch_id=?",
            (branch_id,)
        ).fetchone()

        return Api_mock.Basemodel.BranchResponse(**dict(updated_row))

    finally:
        conn.close()

@app.post(
    "/agent",
    response_model=Api_mock.Basemodel.AgentTokenResponse)
# )but this still runs and blocks if not Admin
def create_agent(data: Api_mock.Basemodel.AgentCreate, user=Depends(require_role("Admin"))):
    conn = _get_conn()
    cursor = conn.cursor()
    try:
        
        if data.user_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,     
                detail="Create the account first",

            )
        all_ccount_ids=cursor.execute(
            "SELECT user_id FROM users WHERE user_id =?", (data.user_id,)
        ).fetchone()
        if all_ccount_ids is None:
            raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,     
                            detail="Create the account first",
            
                        )


        cursor.execute(
            """
            INSERT INTO agents
            (user_id, first_name, last_name, email, phone,
             license_no, branch_id, commission_rate, joined_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_DATE))
            """,
            (
                data.user_id, data.first_name, data.last_name,
                data.email, data.phone, data.license_no,
                data.branch_id, data.commission_rate, data.joined_date,
            )
        )
        new_agent_id = cursor.lastrowid
        record_activity(
            conn,
            event_type="AGENT_CREATE",
            outcome="SUCCESS",
            actor_user_id=user["user_id"],
            resource_type="AGENT",
            resource_id=new_agent_id,
            status_code=201,
        )
        conn.commit()
        row = cursor.execute(
            "SELECT * FROM agents WHERE agent_id = ?", (new_agent_id,)
        ).fetchone()

        token = create_agent_token(new_agent_id)
        return Api_mock.Basemodel.AgentTokenResponse(
            agent=Api_mock.Basemodel.AgentResponse(**dict(row)),
            access_token=token,
        )
    finally:
        conn.close()


@app.get(
    "/agent/{agent_id}",
    response_model=Api_mock.Basemodel.AgentResponse
)
def get_agent(agent_id: int, current_agent: dict = Depends(get_current_agent)):
    # token must have been issued for this specific agent_id
    if current_agent["agent_id"] != agent_id:
        _record_activity(
            event_type="AGENT_READ",
            outcome="DENIED",
            actor_user_id=current_agent["user_id"],
            resource_type="AGENT",
            resource_id=agent_id,
            status_code=403,
        )
        raise HTTPException(status_code=403, detail="Token does not belong to this agent")

    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM agents WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        record_activity(
            conn,
            event_type="AGENT_READ",
            outcome="SUCCESS",
            actor_user_id=current_agent["user_id"],
            resource_type="AGENT",
            resource_id=agent_id,
            status_code=200,
        )
        conn.commit()
        return Api_mock.Basemodel.AgentResponse(**dict(row))
    finally:
        conn.close()


@app.put(
    "/agent/{agent_id}",
    response_model=Api_mock.Basemodel.AgentResponse
)
def update_agent(
    agent_id: int,
    data: Api_mock.Basemodel.AgentUpdate,
    current_agent: dict = Depends(get_current_agent),
):
    if current_agent["agent_id"] != agent_id:
        _record_activity(
            event_type="AGENT_UPDATE",
            outcome="DENIED",
            actor_user_id=current_agent["user_id"],
            resource_type="AGENT",
            resource_id=agent_id,
            status_code=403,
        )
        raise HTTPException(status_code=403, detail="Token does not belong to this agent")

    conn = _get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE agents
            SET first_name=?, last_name=?, email=?, phone=?,
                license_no=?, branch_id=?, commission_rate=?
            WHERE agent_id=?
            """,
            (
                data.first_name, data.last_name, data.email, data.phone,
                data.license_no, data.branch_id, data.commission_rate,
                agent_id,
            )
        )
        if cursor.rowcount == 0:
            record_activity(
                conn,
                event_type="AGENT_UPDATE",
                outcome="DENIED",
                actor_user_id=current_agent["user_id"],
                resource_type="AGENT",
                resource_id=agent_id,
                status_code=404,
            )
            conn.commit()
            raise HTTPException(status_code=404, detail="Agent not found")
        record_activity(
            conn,
            event_type="AGENT_UPDATE",
            outcome="SUCCESS",
            actor_user_id=current_agent["user_id"],
            resource_type="AGENT",
            resource_id=agent_id,
            status_code=200,
        )
        conn.commit()
        row = cursor.execute(
            "SELECT * FROM agents WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        return Api_mock.Basemodel.AgentResponse(**dict(row))
    finally:
        conn.close()


@app.patch(
    "/agent/{agent_id}",
    response_model=Api_mock.Basemodel.AgentResponse
)
def partial_update_agent(
    agent_id: int,
    data: Api_mock.Basemodel.AgentPartialUpdate,
    current_agent: dict = Depends(get_current_agent),
):
    if current_agent["agent_id"] != agent_id:
        _record_activity(
            event_type="AGENT_UPDATE",
            outcome="DENIED",
            actor_user_id=current_agent["user_id"],
            resource_type="AGENT",
            resource_id=agent_id,
            status_code=403,
        )
        raise HTTPException(status_code=403, detail="Token does not belong to this agent")

    conn = _get_conn()
    cursor = conn.cursor()
    try:
        # build SET clause from only the fields that were sent ,  model_dump will give all playload which it is passed
        updates = {k: v for k, v in data.model_dump().items() if v is not None}
        if not updates:
            raise HTTPException(status_code=422, detail="No fields provided to update")

        set_clause = ", ".join(f"{col}=?" for col in updates)
        values = list(updates.values()) + [agent_id]
        cursor.execute(
            f"UPDATE agents SET {set_clause} WHERE agent_id=?",values
            )
        if cursor.rowcount == 0:
            record_activity(
                conn,
                event_type="AGENT_UPDATE",
                outcome="DENIED",
                actor_user_id=current_agent["user_id"],
                resource_type="AGENT",
                resource_id=agent_id,
                status_code=404,
            )
            conn.commit()
            raise HTTPException(status_code=404, detail="Agent not found")
        record_activity(
            conn,
            event_type="AGENT_UPDATE",
            outcome="SUCCESS",
            actor_user_id=current_agent["user_id"],
            resource_type="AGENT",
            resource_id=agent_id,
            status_code=200,
        )
        conn.commit()
        row = cursor.execute(
            "SELECT * FROM agents WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        return Api_mock.Basemodel.AgentResponse(**dict(row))
    finally:
        conn.close()