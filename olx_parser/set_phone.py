import logging
import sys
import json
import re
import time
from database import db_session
import models

logg = logging.getLogger('log.update_realtor_phones.py')


def standardize_phone(phone_str):
    """
    Standardize phone number by removing all non-digit characters and +38 prefix
    """
    # Check if phone_str is None or empty
    if phone_str is None or not phone_str:
        return None

    # Remove all non-digit characters
    digits_only = re.sub(r'\D', '', phone_str)

    # If no digits left, return None
    if not digits_only:
        return None

    # Remove +38 prefix if present
    if digits_only.startswith('38'):
        digits_only = digits_only[2:]

    return digits_only


def update_realtor_phones(json_file_path, batch_size=50):
    """
    Update phone numbers for realtors with platform 'OLX'

    Args:
        json_file_path (str): Path to the JSON file with phone numbers
        batch_size (int): Batch size for committing changes
    """
    start_time = time.time()
    updated_count = 0
    skipped_count = 0
    null_phone_count = 0

    try:
        # Load phone numbers from JSON file
        with open(json_file_path, 'r', encoding='utf-8') as file:
            phone_data = json.load(file)

        logg.info(f"Loaded {len(phone_data)} entries from {json_file_path}")

        with db_session() as session:
            # Get all realtors with platform 'OLX'
            olx_realtors = session.query(models.Realtor).filter(
                models.Realtor.platform == 'OLX'
            ).all()

            logg.info(f"Found {len(olx_realtors)} realtors with platform 'OLX'")

            for i, realtor in enumerate(olx_realtors, 1):
                if realtor.user_id and str(realtor.user_id) in phone_data:
                    # Check if phone exists in the data and is not None
                    if "phone" in phone_data[str(realtor.user_id)] and phone_data[str(realtor.user_id)][
                        "phone"] is not None:
                        raw_phone = phone_data[str(realtor.user_id)]['phone']
                        standardized_phone = standardize_phone(raw_phone)

                        if standardized_phone is not None:
                            print(f"{realtor.user_id}: {raw_phone} -> {standardized_phone}")
                            realtor.phone = standardized_phone
                            updated_count += 1
                        else:
                            null_phone_count += 1
                            logg.debug(f"Skipped realtor ID={realtor.id}, user_id={realtor.user_id}: "
                                       f"invalid phone format: '{raw_phone}'")
                    else:
                        null_phone_count += 1
                        logg.debug(f"Skipped realtor ID={realtor.id}, user_id={realtor.user_id}: "
                                   f"phone is None in data")
                else:
                    skipped_count += 1
                    logg.debug(f"Skipped realtor ID={realtor.id}, user_id={realtor.user_id}: no entry in data")

                # Commit changes in batches
                if i % batch_size == 0:
                    session.commit()
                    logg.info(f"Committed changes for {i} of {len(olx_realtors)} realtors")

            # Commit remaining changes
            if len(olx_realtors) % batch_size != 0:
                session.commit()

            logg.info(f"Total realtors processed: {len(olx_realtors)}")
            logg.info(f"Updated phone numbers: {updated_count}")
            logg.info(f"Skipped (no data entry): {skipped_count}")
            logg.info(f"Skipped (null or invalid phone): {null_phone_count}")

    except Exception as e:
        logg.error(f"Error updating realtor phones: {str(e)}")
        raise

    execution_time = time.time() - start_time
    logg.info(f"Script executed in {execution_time:.2f} seconds")


if __name__ == "__main__":
    try:
        logg.info("Starting realtor phone update process")

        # Default parameters
        json_file_path = "realtors_without_phone.json"
        batch_size = 50

        # Check for command line arguments
        if len(sys.argv) > 1:
            json_file_path = sys.argv[1]

        if len(sys.argv) > 2:
            try:
                batch_size = int(sys.argv[2])
            except ValueError:
                logg.warning(f"Invalid batch size: {sys.argv[2]}. Using default: 50")

        update_realtor_phones(json_file_path, batch_size)

    except Exception as e:
        logg.error(f"Critical error in script execution: {str(e)}")
        sys.exit(1)
