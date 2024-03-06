import argparse
import csv
import tax_lot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=str, help="gain & loss csv file path")
    parser.add_argument("output", type=str, help="output file path, without file extension")
    parser.add_argument("-c", "--cash", type=int, help="vmware share count liquidated for cash")
    parser.add_argument("-s", "--stock", type=int, help="vmware share count liquidated for stock")
    args = parser.parse_args()

    output_file_name = args.output
    output_file = open(output_file_name + ".txt", "w")
    csv_file = open(output_file_name + ".csv", "w")

    if args.cash and args.stock:
        tax_lot.update_global_variable(args.cash, args.stock)

    tax_lot.display_global_variable(output_file)
    tax_lot.load_historical_price()
    tax_lot.load_espp_dates()

    calc_tax(args.input, output_file, csv_file)

    output_file.close()
    csv_file.close()


def calc_tax(input_file_path, output_file, csv_file):
    lots = []
    idx = 3

    avgo_lot = None
    avgo_fractional_share = None
    avgo_acquire_date = None
    avgo_fractional_share_proceeds = None

    # read in gain&loss csv file
    with open(input_file_path, 'r') as file:
        csv_reader = csv.DictReader(file)
        gain_loss_data = [row for row in csv_reader]

    # process each row in csv file
    for row in gain_loss_data:
        if row["Symbol"] == "VMW" and row["Record Type"] == "Sell":
            lot = {"share": int(row["Qty."]), "acquire_date": row["Date Acquired"]}

            # identify unknown type is espp or rs
            plan_type = row["Plan Type"]
            if plan_type == "":
                offer_date = tax_lot.get_espp_offer_date(lot["acquire_date"])
                if offer_date:
                    lot["type"] = "ESPP"
                    lot["offer_date"] = offer_date
                else:
                    lot["type"] = "RS"
            else:
                lot["type"] = plan_type
                if plan_type == "ESPP":
                    lot["offer_date"] = row["Grant Date"]

            lot["sold_date"] = row["Date Sold"]

            # so the per lot tax data in output file can be referred back to corresponding csv row
            lot["row_id"] = idx
            idx = idx + 1

            # so we know which lot is sold before merge
            tax_lot.set_lot_merge_status(lot)
            lot["total_proceeds"] = float(row["Total Proceeds"].strip("$").strip().replace(",", ""))

            if lot["merged"]:
                calc_lot_tax(lot)
            else:
                tax_lot.set_capital_gain_term(lot)

            lots.append(lot)
        elif row["Symbol"] == "AVGO":
            # get avgo fractional share info
            avgo_acquire_date = row["Date Acquired"]
            avgo_fractional_share = float(row["Qty."])
            avgo_fractional_share_proceeds = float(row["Total Proceeds"].strip("$").strip().replace(",", ""))

    # find the lot used for avgo fractional share cost base, calc avgo fractional share cost base
    if avgo_acquire_date:
        avgo_lot = find_avgo_fractional_lot(avgo_acquire_date, lots)

        if avgo_lot is not None:
            avgo_lot["fractional_share"] = avgo_fractional_share
            avgo_lot["fractional_share_proceeds"] = avgo_fractional_share_proceeds
            tax_lot.calc_fractional_share(avgo_lot)
        else:
            print("Failed to find cost base lot for fractional share, acquire date=%s" % avgo_acquire_date)

    total_vmw_share = 0
    total_avgo_share = 0
    total_long_term_proceeds = 0
    total_long_term_cost_base = 0
    total_long_term_capital_gain = 0
    total_short_term_proceeds = 0
    total_short_term_cost_base = 0
    total_short_term_capital_gain = 0

    # compute tax summary of all lots
    for lot in lots:
        if lot["merged"]:
            total_vmw_share = total_vmw_share + lot["share"]
            total_avgo_share = total_avgo_share + lot["avgo_share"]

            if lot["long_term"]:
                total_long_term_proceeds = total_long_term_proceeds + lot["total_proceeds"]
                total_long_term_cost_base = total_long_term_cost_base + lot["total_cost_base"]
                total_long_term_capital_gain = total_long_term_capital_gain + lot["total_capital_gain"]
            else:
                total_short_term_proceeds = total_short_term_proceeds + lot["total_proceeds"]
                total_short_term_cost_base = total_short_term_cost_base + lot["total_cost_base"]
                total_short_term_capital_gain = total_short_term_capital_gain + lot["total_capital_gain"]
        else:
            if lot["long_term"]:
                total_long_term_proceeds = total_long_term_proceeds + lot["total_proceeds"]
            else:
                total_short_term_proceeds = total_short_term_proceeds + lot["total_proceeds"]

    total_proceeds = total_long_term_proceeds + total_short_term_proceeds + avgo_lot["fractional_share_proceeds"]

    # display tax summary of all lots
    output_file.write('{:<35s}{:<.3f}\n'.format("total vmw share:", total_vmw_share))
    output_file.write('{:<35s}{:<.3f}\n'.format("total avgo share:", total_avgo_share))
    output_file.write('{:<35s}${:,.2f}\n\n'.format("total proceeds:", total_proceeds))

    output_file.write('{:<35s}${:,.2f}\n'.format("total short term proceeds:", total_short_term_proceeds))
    output_file.write('{:<35s}${:,.2f}\n'.format("total short term cost base:", total_short_term_cost_base))
    output_file.write(
        '{:<35s}${:,.2f}\n\n'.format("total_short term capital gain:", total_short_term_capital_gain))

    output_file.write('{:<35s}${:,.2f}\n'.format("total long term proceeds:", total_long_term_proceeds))
    output_file.write('{:<35s}${:,.2f}\n'.format("total long term cost base:", total_long_term_cost_base))
    output_file.write('{:<35s}${:,.2f}\n\n'.format("total long term capital gain:", total_long_term_capital_gain))

    # display fractional share info, same info is also displayed in that lot
    if "fractional_share" in avgo_lot:
        output_file.write('{:<35s}{:<d}\n'.format("fractional share cost base lot:", avgo_lot["row_id"]))
        output_file.write('{:<35s}{:<s}\n'.format("acquire date:", avgo_lot["acquire_date"]))
        output_file.write('{:<35s}{:<s}\n'.format("long term:", str(avgo_lot["long_term"])))
        tax_lot.display_fractiona_share(output_file, avgo_lot)

    csv_file.write(tax_lot.generate_csv_header())

    # display tax data for each lot
    for lot in lots:
        output_file.write("\n---------------------- row: %d ----------------------\n" % lot["row_id"])

        if lot["merged"]:
            tax_lot.display_lot_tax(lot, output_file, csv_file)
        else:
            tax_lot.display_not_merged_lot_tax(lot, output_file, csv_file)


def find_avgo_fractional_lot(avgo_acquire_date, lots):
    for lot in lots:
        if lot["acquire_date"] == avgo_acquire_date and lot["merged"]:
            return lot

    return None


def calc_lot_tax(lot):
    # validate required input is present
    if ("type" not in lot) or ("share" not in lot) or ("acquire_date" not in lot):
        raise Exception("Lot misses required info: type, share, acquire_date")

    if lot["type"] == "ESPP":
        lot["offer_date"] = tax_lot.get_espp_offer_date(lot["acquire_date"])
        tax_lot.calc_espp_cost_base(lot)
    elif lot["type"] == "RS":
        tax_lot.calc_rs_cost_base(lot)
    else:
        if "purchase_price" not in lot:
            raise Exception("PURCHASE type lot misses purchase_price info")
        tax_lot.calc_other_cost_base(lot)

    tax_lot.adjust_special_dividend(lot)
    tax_lot.set_capital_gain_term(lot)
    tax_lot.calc_merge_tax_and_avgo_cost_base(lot)
    tax_lot.calc_total(lot)

    if ("fractional_share" in lot) and ("fractional_share_proceeds" in lot):
        tax_lot.calc_fractional_share(lot)


if __name__ == "__main__":
    main()
