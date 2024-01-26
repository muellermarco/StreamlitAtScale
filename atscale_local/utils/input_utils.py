from atscale.errors import atscale_errors


def get_string_input(
    msg: str,
):
    """Returns any user input as a string. Captures keyboard interrupt (ctrl c) to return None.

    Args:
        msg (str): The message to display requesting user input

    Returns:
        str: user input as a string or None if they enter keyboard interrupt
    """
    try:
        return input(msg)
    except KeyboardInterrupt:
        # do something special?
        return None
    except:
        return None


def choose_id_and_name_from_dict_list(
    dcts: list, prompt: str = None, id_key: str = "id", name_key: str = "name"
):
    """Given a list of dictionaries, we assume there is an id and name element and print them out then ask for user input to select one of them.

    Args:
        dcts (list): list of python dictionaries
        prompt (str): custom prompt string
        id_col (str, optional): custom id key for the dict. Defaults to id
        name_col (str, optional): custom name key for the dict. Defaults to name

    Returns:
        dict: the dict associated with the user input selection or None if they cancel somehow
    """
    if prompt:
        print(prompt)
    else:
        print("Please choose:")

    if len(dcts) < 1:
        raise atscale_errors.UserError("No valid options to choose from")

    if len(dcts) == 1:
        print(
            f'Automatically selecting only option: "ID: {dcts[0][id_key]}: Name: {dcts[0][name_key]}"'
        )
        return dcts[0]

    for i, dct in enumerate(dcts):
        print(f"{i+1} ID: {dct[id_key]}: Name: {dct[name_key]}")

    try:
        # exception could be raised by cast to int, interrupt, etc.
        i = int(input("Enter number: ")) - 1
    except KeyboardInterrupt:
        # do something special?
        return None
    except:
        raise

    if -1 < i < len(dcts):
        return dcts[i]
    else:
        # Else they picked a number not shown. We could recurse and keep asking but I'll just return None
        raise atscale_errors.UserError(
            f"The provided input number {i + 1} is out of range 1 - {len(dcts)}"
        )


def prompt_yes_no(
    question: str,
) -> bool:
    """Returns a boolean value indicating the user's answer to the yes/no question passed as an argument.

    Args:
        question (str): The question to which the user responds

    Returns:
        bool: The truth value corresponding to the user's answer
              (i.e. True for 'yes'/'y', False for 'no'/'n', None otherwise)
    """
    try:
        answer: str = input(f"{question} y/n: ").lower()
        if answer in ["yes", "y"]:
            return True
        elif answer in ["no", "n"]:
            return False
        else:
            return prompt_yes_no(question)
    except KeyboardInterrupt:
        # Do something special?
        return None
    except:
        return None
