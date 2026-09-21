from backend.app import create_app
from tests.fakes import FakeModel

model = FakeModel()
app = create_app(model=model)
model.store = app.state.store
