import sys

# List of users who successfully received the message based on the logs
sent_users = {
    "@llsasha", "@moonshine_er", "@an_geroeva", "@name_from_russia", "@katialunina22", 
    "@k_gorka333", "@Canter_ville", "@Marktraders", "@kristina_zhitneva", "@ilya_fair", 
    "@one_xman", "@e_lubi", "@makarovamaryy", "@Olya_admin1", "@lamborgeneey", 
    "@marina_semashko", "@feoandr", "@hypnooozework", "@Anastasia614", "@alekseevmaxx", 
    "@polpol05200", "@and_digital", "@Lil_Frize", "@maximroshkov", "@MaxMade_des", 
    "@linariapoli", "@anastasiaa_redkina", "@whitebelaya", "@naza_mngr", "@lm_Radik", 
    "@vidnoee", "@anas_tes", "@alina_rodionova_ad", "@Kalemato", "@grandverner", 
    "@ave821", "@LehaRus", "@Niyarasufyanova", "@rafaelabilov", "@Alina00812", 
    "@adimder", "@ennnuii", "@leaveinsilence27", "@deniboff", "@bellondie", "@LanaMaxwell"
}

# Also remove invalid user
invalid_users = {"@pepetothemoonn"}

to_remove = sent_users.union(invalid_users)

def update_list():
    input_file = "test_users.txt"
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f if line.strip()]
        
        original_count = len(lines)
        remaining_lines = []
        
        # We need to remove only the *instances* that were sent.
        # But wait, the list had duplicates and we sent to duplicates.
        # Account 1 sent to llsasha, Account 3 sent to llsasha (later in log).
        # Actually Account 3 log says: "[Account_3] Sending to @llsasha (6/20)... ✅ Sent to @llsasha"
        # So duplicates were processed.
        
        # Strategy: Remove ALL occurrences of users who have been sent a message effectively.
        # If a user is in `sent_users`, they got the message at least once. 
        # We don't want to spam them again even if they are duplicated in the source list?
        # The user asked: "update list of leads who have not received message".
        # If I remove all instances of @llsasha, that satisfies "not received".
        
        for line in lines:
            # Handle potential backslashes or cleanup if needed, though we rely on exact match or normalized
            # User specifically asked to FIX the output format to not have backslashes.
            # So when writing back, we should ensure 'cleaned' version is written if intended.
            # BUT wait, the user's query is "Fix the output of the list of leads" (probably referring to my previous message).
            # If they mean the FILE itself, I should strip backslashes when writing.
            
            clean_line = line.strip().replace('\\', '')
            # Check if this user is in the sent list (normalized)
            if clean_line not in to_remove:
                remaining_lines.append(clean_line) # Append CLEAN line
                
        with open(input_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(remaining_lines) + '\n')
            
        print(f"Updated {input_file}. Removed {original_count - len(remaining_lines)} entries. Remaining: {len(remaining_lines)}")
        
    except FileNotFoundError:
        print("test_users.txt not found")

if __name__ == "__main__":
    update_list()

