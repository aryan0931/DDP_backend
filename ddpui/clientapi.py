from ninja import NinjaAPI
from ninja.errors import HttpError
from datetime import datetime
from .timezone import IST
from uuid import uuid4

from typing import List

from .ddplogger import logger
from .auth import LoginData, ClientAuthBearer

clientapi = NinjaAPI()
# http://127.0.0.1:8000/api/docs

from .clientuser import ClientUser, ClientUserCreate, ClientUserUpdate, ClientUserResponse
from .clientuser import InvitationSchema, Invitation, AcceptInvitationSchema
from .clientorg import ClientOrg, ClientOrgSchema

from .airbyteschemas import AirbyteWorkspaceCreate, AirbyteWorkspace
from .airbyteschemas import AirbyteSourceCreate, AirbyteDestinationCreate, AirbyteConnectionCreate

from . import airbyteapi

# ====================================================================================================
@clientapi.get("/currentuser", auth=ClientAuthBearer(), response=ClientUserResponse)
def currentuser(request):
  return request.auth

# ====================================================================================================
@clientapi.post("/createuser/", response=ClientUserResponse)
def createuser(request, payload: ClientUserCreate):
  if ClientUser.objects.filter(email=payload.email).exists():
    raise HttpError(400, f"user having email {payload.email} exists")
  user = ClientUser.objects.create(**payload.dict())
  logger.info(f"created user {payload.email}")
  return user

# ====================================================================================================
@clientapi.post("/login/")
def login(request, payload: LoginData):
  if payload.password == 'password':
    user = ClientUser.objects.filter(email=payload.email).first()
    if user:
      token = f"fake-auth-token:{user.id}"
      logger.info("returning auth token " + token)
      return {'token': token}
  raise HttpError(400, "login denied")

# ====================================================================================================
@clientapi.get("/users", response=List[ClientUserResponse], auth=ClientAuthBearer())
def users(request):
  assert(request.auth)
  user = request.auth
  if user.clientorg is None:
    raise HttpError(400, "no associated org")
  return ClientUser.objects.filter(clientorg=user.clientorg)

# ====================================================================================================
@clientapi.post("/updateuser/", response=ClientUserResponse, auth=ClientAuthBearer())
def updateuser(request, payload: ClientUserUpdate):
  assert(request.auth)
  user = request.auth
  if payload.email:
    user.email = payload.email
  if payload.active is not None:
    user.active = payload.active
  user.save()
  logger.info(f"updated user {user.email}")
  return user

# ====================================================================================================
@clientapi.post('/client/create/', response=ClientOrgSchema, auth=ClientAuthBearer())
def createclient(request, payload: ClientOrgSchema):
  logger.info(payload)
  user = request.auth
  if user.clientorg:
    raise HttpError(400, "user already has an associated client")
  clientorg = ClientOrg.objects.filter(name=payload.name).first()
  if clientorg:
    raise HttpError(400, "client org already exists")
  clientorg = ClientOrg.objects.create(**payload.dict())
  user.clientorg = clientorg
  user.save()
  return clientorg

# ====================================================================================================
@clientapi.post('/user/invite/', response=InvitationSchema, auth=ClientAuthBearer())
def inviteuser(request, payload: InvitationSchema):
  if request.auth.clientorg is None:
    raise HttpError(400, "an associated organization is required")
  x = Invitation.objects.filter(invited_email=payload.invited_email).first()
  if x:
    logger.error(f"{payload.invited_email} has already been invited by {x.invited_by} on {x.invited_on.strftime('%Y-%m-%d')}")
    raise HttpError(400, f'{payload.invited_email} has already been invited')

  payload.invited_by = ClientUserResponse(email=request.auth.email, clientorg=request.auth.clientorg, active=request.auth.active)
  payload.invited_on = datetime.now(IST)
  payload.invite_code = str(uuid4())
  x = Invitation.objects.create(
    invited_email=payload.invited_email,
    invited_by=request.auth,
    invited_on=payload.invited_on,
    invite_code=payload.invite_code,
  )
  logger.info('created Invitation')
  return payload

# ====================================================================================================
# the invitee will get a hyperlink via email, clicking will take them to the UI where they will choose
# a password, then click a button POSTing to this endpoint
@clientapi.get('/user/getinvitedetails/{invite_code}', response=InvitationSchema)
def getinvitedetails(request, invite_code):
  x = Invitation.objects.filter(invite_code=invite_code).first()
  if x is None:
    raise HttpError(400, "invalid invite code")
  return InvitationSchema.from_invitation(x)

# ====================================================================================================
@clientapi.post('/user/acceptinvite/', response=ClientUserResponse)
def acceptinvite(request, payload: AcceptInvitationSchema):
  x = Invitation.objects.filter(invite_code=payload.invite_code).first()
  if x is None:
    raise HttpError(400, "invalid invite code")
  clientuser = ClientUser.objects.filter(email=x.invited_email, clientorg=x.invited_by.clientorg).first()
  if not clientuser:
    logger.info(f"creating invited user {x.invited_email} for {x.invited_by.clientorg.name}")
    clientuser = ClientUser.objects.create(email=x.invited_email, clientorg=x.invited_by.clientorg)
  return clientuser
  
# ====================================================================================================
@clientapi.post('/airbyte/detatchworkspace/', auth=ClientAuthBearer())
def airbyte_detatchworkspace(request):
  user = request.auth
  if user.clientorg is None:
    raise HttpError(400, "create an organization first")
  if user.clientorg.airbyte_workspace_id is None:
    raise HttpError(400, "org already has no workspace")
  
  user.clientorg.airbyte_workspace_id = None
  user.clientorg.save()

  return {"success": 1}

# ====================================================================================================
@clientapi.post('/airbyte/createworkspace/', response=AirbyteWorkspace, auth=ClientAuthBearer())
def airbyte_createworkspace(request, payload: AirbyteWorkspaceCreate):
  user = request.auth
  if user.clientorg is None:
    raise HttpError(400, "create an organization first")
  if user.clientorg.airbyte_workspace_id is not None:
    raise HttpError(400, "org already has a workspace")

  workspace = airbyteapi.createworkspace(payload.name)

  user.clientorg.airbyte_workspace_id = workspace['workspaceId']
  user.clientorg.save()

  return AirbyteWorkspace(
    name=workspace['name'],
    workspaceId=workspace['workspaceId'],
    initialSetupComplete=workspace['initialSetupComplete']
  )

# ====================================================================================================
@clientapi.get('/airbyte/getsourcedefinitions', auth=ClientAuthBearer())
def airbyte_getsources(request):
  user = request.auth
  if user.clientorg is None:
    raise HttpError(400, "create an organization first")
  if user.clientorg.airbyte_workspace_id is None:
    raise HttpError(400, "create an airbyte workspace first")

  r = airbyteapi.getsourcedefinitions(user.clientorg.airbyte_workspace_id)
  logger.debug(r)
  return r

@clientapi.get('/airbyte/getsourcedefinitionspecification/{sourcedef_id}', auth=ClientAuthBearer())
def airbyte_getsourcedefinitionspecification(request, sourcedef_id):
  user = request.auth
  if user.clientorg is None:
    raise HttpError(400, "create an organization first")
  if user.clientorg.airbyte_workspace_id is None:
    raise HttpError(400, "create an airbyte workspace first")

  r = airbyteapi.getsourcedefinitionspecification(user.clientorg.airbyte_workspace_id, sourcedef_id)
  logger.debug(r)
  return r

@clientapi.post('/airbyte/createsource/', auth=ClientAuthBearer())
def airbyte_createsource(request, payload: AirbyteSourceCreate):
  user = request.auth
  if user.clientorg is None:
    raise HttpError(400, "create an organization first")
  if user.clientorg.airbyte_workspace_id is None:
    raise HttpError(400, "create an airbyte workspace first")

  source = airbyteapi.createsource(user.clientorg.airbyte_workspace_id, payload.name, payload.sourcedef_id, payload.config)
  logger.info("created source having id " + source['sourceId'])
  return {'source_id': source['sourceId']}

@clientapi.post('/airbyte/checksource/{source_id}/', auth=ClientAuthBearer())
def airbyte_checksource(request, source_id):
  user = request.auth
  if user.clientorg is None:
    raise HttpError(400, "create an organization first")
  if user.clientorg.airbyte_workspace_id is None:
    raise HttpError(400, "create an airbyte workspace first")

  r = airbyteapi.checksourceconnection(user.clientorg.airbyte_workspace_id, source_id)
  logger.debug(r)
  return r

@clientapi.get('/airbyte/getsources', auth=ClientAuthBearer())
def airbyte_getsources(request):
  user = request.auth
  if user.clientorg is None:
    raise HttpError(400, "create an organization first")
  if user.clientorg.airbyte_workspace_id is None:
    raise HttpError(400, "create an airbyte workspace first")

  r = airbyteapi.getsources(user.clientorg.airbyte_workspace_id)
  logger.debug(r)
  return r

@clientapi.get('/airbyte/getsource/{source_id}', auth=ClientAuthBearer())
def airbyte_getsources(request, source_id):
  user = request.auth
  if user.clientorg is None:
    raise HttpError(400, "create an organization first")
  if user.clientorg.airbyte_workspace_id is None:
    raise HttpError(400, "create an airbyte workspace first")

  r = airbyteapi.getsource(user.clientorg.airbyte_workspace_id, source_id)
  logger.debug(r)
  return r

@clientapi.get('/airbyte/getsourceschemacatalog/{source_id}', auth=ClientAuthBearer())
def airbyte_getsourceschemacatalog(request, source_id):
  user = request.auth
  if user.clientorg is None:
    raise HttpError(400, "create an organization first")
  if user.clientorg.airbyte_workspace_id is None:
    raise HttpError(400, "create an airbyte workspace first")

  r = airbyteapi.getsourceschemacatalog(user.clientorg.airbyte_workspace_id, source_id)
  logger.debug(r)
  return r

# =======
@clientapi.get('/airbyte/getdestinationdefinitions', auth=ClientAuthBearer())
def airbyte_getdestinations(request):
  user = request.auth
  if user.clientorg is None:
    raise HttpError(400, "create an organization first")
  if user.clientorg.airbyte_workspace_id is None:
    raise HttpError(400, "create an airbyte workspace first")

  r = airbyteapi.getdestinationdefinitions(user.clientorg.airbyte_workspace_id)
  logger.debug(r)
  return r

@clientapi.get('/airbyte/getdestinationdefinitionspecification/{destinationdef_id}', auth=ClientAuthBearer())
def airbyte_getdestinationdefinitionspecification(request, destinationdef_id):
  user = request.auth
  if user.clientorg is None:
    raise HttpError(400, "create an organization first")
  if user.clientorg.airbyte_workspace_id is None:
    raise HttpError(400, "create an airbyte workspace first")

  r = airbyteapi.getdestinationdefinitionspecification(user.clientorg.airbyte_workspace_id, destinationdef_id)
  logger.debug(r)
  return r

@clientapi.post('/airbyte/createdestination/', auth=ClientAuthBearer())
def airbyte_createsource(request, payload: AirbyteDestinationCreate):
  user = request.auth
  if user.clientorg is None:
    raise HttpError(400, "create an organization first")
  if user.clientorg.airbyte_workspace_id is None:
    raise HttpError(400, "create an airbyte workspace first")

  destination = airbyteapi.createdestination(user.clientorg.airbyte_workspace_id, payload.name, payload.destinationdef_id, payload.config)
  logger.info("created destination having id " + destination['destinationId'])
  return {'destination_id': destination['destinationId']}

@clientapi.post('/airbyte/checkdestination/{destination_id}/', auth=ClientAuthBearer())
def airbyte_checkdestination(request, destination_id):
  user = request.auth
  if user.clientorg is None:
    raise HttpError(400, "create an organization first")
  if user.clientorg.airbyte_workspace_id is None:
    raise HttpError(400, "create an airbyte workspace first")

  r = airbyteapi.checkdestinationconnection(user.clientorg.airbyte_workspace_id, destination_id)
  logger.debug(r)
  return r

@clientapi.get('/airbyte/getdestinations', auth=ClientAuthBearer())
def airbyte_getdestinations(request):
  user = request.auth
  if user.clientorg is None:
    raise HttpError(400, "create an organization first")
  if user.clientorg.airbyte_workspace_id is None:
    raise HttpError(400, "create an airbyte workspace first")

  r = airbyteapi.getdestinations(user.clientorg.airbyte_workspace_id)
  logger.debug(r)
  return r

@clientapi.get('/airbyte/getdestination/{destination_id}', auth=ClientAuthBearer())
def airbyte_getdestinations(request, destination_id):
  user = request.auth
  if user.clientorg is None:
    raise HttpError(400, "create an organization first")
  if user.clientorg.airbyte_workspace_id is None:
    raise HttpError(400, "create an airbyte workspace first")

  r = airbyteapi.getdestination(user.clientorg.airbyte_workspace_id, destination_id)
  logger.debug(r)
  return r

@clientapi.get('/airbyte/getconnections', auth=ClientAuthBearer())
def airbyte_getconnections(request):
  user = request.auth
  if user.clientorg is None:
    raise HttpError(400, "create an organization first")
  if user.clientorg.airbyte_workspace_id is None:
    raise HttpError(400, "create an airbyte workspace first")

  r = airbyteapi.getconnections(user.clientorg.airbyte_workspace_id)
  logger.debug(r)
  return r

@clientapi.get('/airbyte/getconnection/{connection_id}', auth=ClientAuthBearer())
def airbyte_getconnections(request, connection_id):
  user = request.auth
  if user.clientorg is None:
    raise HttpError(400, "create an organization first")
  if user.clientorg.airbyte_workspace_id is None:
    raise HttpError(400, "create an airbyte workspace first")

  r = airbyteapi.getconnection(user.clientorg.airbyte_workspace_id, connection_id)
  logger.debug(r)
  return r

@clientapi.post('/airbyte/createconnection/', auth=ClientAuthBearer())
def airbyte_createconnection(request, payload: AirbyteConnectionCreate):
  user = request.auth
  if user.clientorg is None:
    raise HttpError(400, "create an organization first")
  if user.clientorg.airbyte_workspace_id is None:
    raise HttpError(400, "create an airbyte workspace first")
  
  if len(payload.streamnames) == 0:
    raise HttpError(400, "must specify stream names")

  r = airbyteapi.createconnection(user.clientorg.airbyte_workspace_id, payload)
  logger.debug(r)
  return r

@clientapi.post('/airbyte/syncconnection/{connection_id}/', auth=ClientAuthBearer())
def airbyte_syncconnection(request, connection_id):
  user = request.auth
  if user.clientorg is None:
    raise HttpError(400, "create an organization first")
  if user.clientorg.airbyte_workspace_id is None:
    raise HttpError(400, "create an airbyte workspace first")
  
  airbyteapi.syncconnection(user.clientorg.airbyte_workspace_id, connection_id)
