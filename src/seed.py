"""
Seeds the org structure. This is DATA, not schema — adding a new team or
advisor later is just another call to add_advisor(), never a migration.
"""
from src.models import init_db, get_session, Org, Team, Advisor


def add_advisor(session, org_name, team_name, team_leader, advisor_name):
    org = session.query(Org).filter_by(name=org_name).first()
    if not org:
        org = Org(name=org_name)
        session.add(org)
        session.flush()

    team = session.query(Team).filter_by(name=team_name, org_id=org.id).first()
    if not team:
        team = Team(name=team_name, org_id=org.id, team_leader_name=team_leader)
        session.add(team)
        session.flush()

    advisor = session.query(Advisor).filter_by(name=advisor_name, team_id=team.id).first()
    if not advisor:
        advisor = Advisor(name=advisor_name, team_id=team.id)
        session.add(advisor)
        session.flush()

    return advisor


def main():
    init_db("data/fitnova.db")
    session = get_session("data/fitnova.db")

    # Matches the advisors used in our synthetic test calls
    add_advisor(session, "FitNova", "Pod Alpha", "Meera Shah", "Priya")
    add_advisor(session, "FitNova", "Pod Alpha", "Meera Shah", "Vikram")
    add_advisor(session, "FitNova", "Pod Beta", "Karan Mehta", "Anjali")

    session.commit()
    print("Seeded org structure:")
    for org in session.query(Org).all():
        for team in org.teams:
            print(f"  {org.name} > {team.name} (lead: {team.team_leader_name})")
            for adv in team.advisors:
                print(f"    - {adv.name} (id={adv.id})")


if __name__ == "__main__":
    main()
