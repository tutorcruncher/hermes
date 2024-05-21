async def get_next_sales_person(admins, latest_sales_person_id):
    """
    @param admins: a list of Admin objects
    @param latest_sales_person_id: the ID of the latest sales Admin object
    @return: the ID of the next sales Admin object
    """
    admin_ids = [a.id async for a in admins.filter(is_sales_person=True).order_by('id')]
    if latest_sales_person_id:
        try:
            next_person_id = admin_ids[admin_ids.index(latest_sales_person_id) + 1]
        except (IndexError, ValueError):
            next_person_id = admin_ids[0]
    else:
        next_person_id = admin_ids[0]
    return next_person_id
