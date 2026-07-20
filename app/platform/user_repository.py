from .enums import UserStatus
from .errors import UserAlreadyExistsError, UserNotFoundError
from .models import User, now_iso
from .repository import JsonRepository


class UserRepository:
    def __init__(self, repo: JsonRepository[User] | None = None):
        self.repo = repo or JsonRepository("users.json", User)

    def create(self, user: User) -> User:
        users = self.repo.all()
        if any(existing.normalized_email == user.normalized_email and existing.status != UserStatus.DELETED for existing in users):
            raise UserAlreadyExistsError("user already exists")
        users.append(user)
        self.repo.replace_all(users)
        return user

    def get_by_id(self, user_id: str) -> User:
        for user in self.repo.all():
            if user.user_id == user_id:
                return user
        raise UserNotFoundError("user not found")

    def get_by_normalized_email(self, normalized_email: str) -> User | None:
        for user in self.repo.all():
            if user.normalized_email == normalized_email and user.status != UserStatus.DELETED:
                return user
        return None

    def list(self, *, limit: int = 50, offset: int = 0, status: UserStatus | None = None) -> list[User]:
        users = [user for user in self.repo.all() if status is None or user.status == status]
        return users[offset : offset + min(limit, 100)]

    def update(self, user: User) -> User:
        users = self.repo.all()
        for index, existing in enumerate(users):
            if existing.user_id == user.user_id:
                user.updated_at = now_iso()
                user.version += 1
                users[index] = user
                self.repo.replace_all(users)
                return user
        raise UserNotFoundError("user not found")

    def disable(self, user_id: str) -> User:
        user = self.get_by_id(user_id)
        user.status = UserStatus.DISABLED
        user.disabled_at = now_iso()
        return self.update(user)


user_repository = UserRepository()
