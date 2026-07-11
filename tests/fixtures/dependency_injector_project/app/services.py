from app.repositories import SqlRepository

class DataService:
    def __init__(self, repository: SqlRepository):
        self.repository = repository

    def fetch(self):
        return self.repository.get_data()
