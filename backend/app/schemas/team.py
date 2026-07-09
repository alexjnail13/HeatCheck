from pydantic import BaseModel


class TeamResponse(BaseModel):
    id: int
    nba_team_id: int
    abbreviation: str
    full_name: str
    city: str
    state: str
    conference: str
    division: str

    class Config:
        from_attributes = True