import threading
import time
from concurrent import futures
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel
from lxml import etree

import grpc

from .storage import Storage, Note
import notes_pb2, notes_pb2_grpc

class NotesServiceServicer(notes_pb2_grpc.NotesServiceServicer):
    def __init__(self, storage: Storage):
        self.storage = storage

    def _note_to_proto(self, n: Note) -> notes_pb2.Note:
        return notes_pb2.Note(
            id=n.id,
            title=n.title,
            description=n.description,
            created_at=n.created_at.isoformat() + "Z",
            updated_at=n.updated_at.isoformat() + "Z",
        )

    def CreateNote(self, request, context):
        n = self.storage.create_note(request.title, request.description)
        return notes_pb2.CreateNoteResponse(note=self._note_to_proto(n))

    def GetNote(self, request, context):
        n = self.storage.get_note(request.id)
        if not n:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("note not found")
            return notes_pb2.GetNoteResponse()
        return notes_pb2.GetNoteResponse(note=self._note_to_proto(n))

    def ListNotes(self, request, context):
        notes = [self._note_to_proto(n) for n in self.storage.list_notes()]
        return notes_pb2.ListNotesResponse(notes=notes)

    def UpdateNoteDescription(self, request, context):
        n = self.storage.update_description(request.id, request.description)
        if not n:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("note not found")
            return notes_pb2.UpdateNoteDescriptionResponse()
        return notes_pb2.UpdateNoteDescriptionResponse(
            note=self._note_to_proto(n)
        )

    def DeleteNote(self, request, context):
        ok = self.storage.delete_note(request.id)
        if not ok:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("note not found")
        return notes_pb2.DeleteNoteResponse()

    def Health(self, request, context):
        if self.storage.health():
            return notes_pb2.HealthResponse()
        context.set_code(grpc.StatusCode.UNAVAILABLE)
        context.set_details("storage unavailable")
        return notes_pb2.HealthResponse()

def run_grpc_server(storage: Storage):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    notes_pb2_grpc.add_NotesServiceServicer_to_server(
        NotesServiceServicer(storage), server
    )
    server.add_insecure_port("[::]:50051")
    server.start()
    print("[gRPC] listening on :50051")
    server.wait_for_termination()

app = FastAPI()
storage = Storage()

def start_grpc_background():
    t = threading.Thread(target=run_grpc_server, args=(storage,), daemon=True)
    t.start()

@app.on_event("startup")
def on_startup():
    start_grpc_background()

class NoteCreate(BaseModel):
    title: str
    description: str

class NoteUpdate(BaseModel):
    description: str

class NoteOut(BaseModel):
    id: str
    title: str
    description: str
    created_at: datetime
    updated_at: datetime

@app.get("/health")
def health():
    if storage.health():
        return {"status": "ok"}
    raise HTTPException(status_code=503, detail="storage unavailable")

@app.post("/notes", response_model=NoteOut, status_code=201)
def create_note(payload: NoteCreate):
    n = storage.create_note(payload.title, payload.description)
    return n

@app.get("/notes", response_model=list[NoteOut])
def list_notes():
    return storage.list_notes()

@app.get("/notes/{note_id}", response_model=NoteOut)
def get_note(note_id: str):
    n = storage.get_note(note_id)
    if not n:
        raise HTTPException(status_code=404, detail="note not found")
    return n

@app.patch("/notes/{note_id}", response_model=NoteOut)
def update_note(note_id: str, payload: NoteUpdate):
    n = storage.update_description(note_id, payload.description)
    if not n:
        raise HTTPException(status_code=404, detail="note not found")
    return n

@app.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: str):
    ok = storage.delete_note(note_id)
    if not ok:
        raise HTTPException(status_code=404, detail="note not found")
    return Response(status_code=204)

@app.post("/soap")
async def soap_endpoint(request: Request):
    body = await request.body()
    try:
        root = etree.fromstring(body)
    except Exception:
        return Response(
            content=soap_fault("Client", "Invalid XML"),
            media_type="text/xml",
            status_code=400,
        )

    ns = {"soap": "http://schemas.xmlsoap.org/soap/envelope/"}
    body_el = root.find("soap:Body", ns)
    if body_el is None or len(body_el) == 0:
        return Response(
            content=soap_fault("Client", "No SOAP body"),
            media_type="text/xml",
            status_code=400,
        )

    op = body_el[0].tag.split("}")[-1]

    if op == "CreateNote":
        title = body_el[0].findtext(".//Title") or ""
        desc = body_el[0].findtext(".//Description") or ""
        n = storage.create_note(title, desc)
        resp_xml = f"""
        <CreateNoteResponse>
          <Note>
            <Id>{n.id}</Id>
            <Title>{n.title}</Title>
            <Description>{n.description}</Description>
            <CreatedAt>{n.created_at.isoformat()}Z</CreatedAt>
            <UpdatedAt>{n.updated_at.isoformat()}Z</UpdatedAt>
          </Note>
        </CreateNoteResponse>
        """
    elif op == "GetNote":
        note_id = body_el[0].findtext(".//Id") or ""
        n = storage.get_note(note_id)
        if not n:
            return Response(
                content=soap_fault("Client", "Note not found"),
                media_type="text/xml",
                status_code=404,
            )
        resp_xml = f"""
        <GetNoteResponse>
          <Note>
            <Id>{n.id}</Id>
            <Title>{n.title}</Title>
            <Description>{n.description}</Description>
            <CreatedAt>{n.created_at.isoformat()}Z</CreatedAt>
            <UpdatedAt>{n.updated_at.isoformat()}Z</UpdatedAt>
          </Note>
        </GetNoteResponse>
        """
    elif op == "ListNotes":
        notes = storage.list_notes()
        items = []
        for n in notes:
            items.append(f"""
            <Note>
              <Id>{n.id}</Id>
              <Title>{n.title}</Title>
              <Description>{n.description}</Description>
              <CreatedAt>{n.created_at.isoformat()}Z</CreatedAt>
              <UpdatedAt>{n.updated_at.isoformat()}Z</UpdatedAt>
            </Note>
            """)
        resp_xml = "<ListNotesResponse>" + "".join(items) + "</ListNotesResponse>"
    elif op == "UpdateNoteDescription":
        note_id = body_el[0].findtext(".//Id") or ""
        desc = body_el[0].findtext(".//Description") or ""
        n = storage.update_description(note_id, desc)
        if not n:
            return Response(
                content=soap_fault("Client", "Note not found"),
                media_type="text/xml",
                status_code=404,
            )
        resp_xml = f"""
        <UpdateNoteDescriptionResponse>
          <Note>
            <Id>{n.id}</Id>
            <Title>{n.title}</Title>
            <Description>{n.description}</Description>
            <CreatedAt>{n.created_at.isoformat()}Z</CreatedAt>
            <UpdatedAt>{n.updated_at.isoformat()}Z</UpdatedAt>
          </Note>
        </UpdateNoteDescriptionResponse>
        """
    elif op == "DeleteNote":
        note_id = body_el[0].findtext(".//Id") or ""
        ok = storage.delete_note(note_id)
        if not ok:
            return Response(
                content=soap_fault("Client", "Note not found"),
                media_type="text/xml",
                status_code=404,
            )
        resp_xml = "<DeleteNoteResponse><Status>ok</Status></DeleteNoteResponse>"
    else:
        return Response(
            content=soap_fault("Client", f"Unknown operation {op}"),
            media_type="text/xml",
            status_code=400,
        )

    envelope = f"""<?xml version="1.0"?>
    <Envelope xmlns="http://schemas.xmlsoap.org/soap/envelope/">
      <Body>{resp_xml}</Body>
    </Envelope>
    """
    return Response(content=envelope, media_type="text/xml")

def soap_fault(code: str, message: str) -> str:
    return f"""<?xml version="1.0"?>
    <Envelope xmlns="http://schemas.xmlsoap.org/soap/envelope/">
      <Body>
        <Fault>
          <faultcode>{code}</faultcode>
          <faultstring>{message}</faultstring>
        </Fault>
      </Body>
    </Envelope>
    """
