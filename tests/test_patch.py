"""
Tests for patch.py commands.
"""

from app.main_app.models import Contact
from patch import fix_repeated_contact_names


class TestFixRepeatedContactNames:
    """Names repeated by #418 are de-duplicated, other names are left alone"""

    async def test_fix_repeated_contact_names(self, db, test_company):
        repeated = db.create(Contact(first_name='john', last_name='john john Smith', company_id=test_company.id))
        jumped = db.create(
            Contact(first_name='john', last_name='john Smith john john Smith', company_id=test_company.id)
        )
        lowercase = db.create(Contact(first_name='mary', last_name='Jones', company_id=test_company.id))
        capitalised = db.create(Contact(first_name='Ali', last_name='Ali Khan', company_id=test_company.id))
        no_capital = db.create(Contact(first_name='lee', last_name='lee', company_id=test_company.id))

        await fix_repeated_contact_names(db)
        db.commit()

        assert (repeated.first_name, repeated.last_name) == ('john', 'Smith')
        assert (jumped.first_name, jumped.last_name) == ('john', 'Smith')
        assert (lowercase.first_name, lowercase.last_name) == ('mary', 'Jones')
        assert (capitalised.first_name, capitalised.last_name) == ('Ali', 'Ali Khan')
        assert (no_capital.first_name, no_capital.last_name) == ('lee', 'lee')
