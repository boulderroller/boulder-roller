-- Deduct CAL from user_state with guard against negative balances
CREATE OR REPLACE FUNCTION public.deduct_cal(p_user_id uuid, p_amount numeric)
RETURNS void AS $$
BEGIN
    UPDATE public.user_state
    SET cal_balance = cal_balance - p_amount,
        updated_at = now()
    WHERE user_id = p_user_id
      AND cal_balance >= p_amount;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Insufficient CAL balance';
    END IF;
END;
$$ LANGUAGE plpgsql;
