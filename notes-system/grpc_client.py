import grpc
import notes_pb2
import notes_pb2_grpc
from pathlib import Path

def main():
    cert_path = Path("lb/certs/lb.crt")
    root_cert = cert_path.read_bytes()

    creds = grpc.ssl_channel_credentials(root_certificates=root_cert)

    options = (
        ("grpc.ssl_target_name_override", "python-lb"),
    )

    with grpc.secure_channel("localhost:8444", creds, options) as channel:
        stub = notes_pb2_grpc.NotesServiceStub(channel)

        try:
            stub.Health(notes_pb2.HealthRequest(), timeout=2.0)
            print("gRPC Health: OK")
        except Exception as e:
            print("gRPC Health failed:", e)
            return

        resp = stub.ListNotes(notes_pb2.ListNotesRequest(), timeout=2.0)
        print("gRPC ListNotes, count =", len(resp.notes))
        for n in resp.notes:
            print("-", n.id, n.title, n.description)

if __name__ == "__main__":
    main()
