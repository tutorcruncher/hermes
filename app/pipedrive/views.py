async def callback():
    """
    Used to updated TC whenever a deal is updated in pipedrive.
    If a Person changes:
    - Do nothing in TC
    - Do nothing in Hermes
    If an Organisation changes:
    - Do nothing in TC
    - Do nothing in Hermes
    If a Deal changes:
    - Update the Cligency in Meta with:
      - The new stage
      - The new link to PD
    - Update the Deal in Hermes with:
      - The new stage
      - The new status
    """
    pass
