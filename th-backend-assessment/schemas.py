from typing import Optional
from pydantic import BaseModel, Field

class ShipmentDetails(BaseModel):
    id: str = Field(..., description="The ID of the email")
    product_line: Optional[str] = Field(None, description="Product line, e.g., pl_sea_import_lcl")
    origin_port_code: Optional[str] = Field(None, description="UN/LOCODE for the origin port")
    origin_port_name: Optional[str] = Field(None, description="Name of the origin port")
    destination_port_code: Optional[str] = Field(None, description="UN/LOCODE for the destination port")
    destination_port_name: Optional[str] = Field(None, description="Name of the destination port")
    incoterm: Optional[str] = Field(None, description="Incoterm, e.g., FOB, CIF")
    cargo_weight_kg: Optional[float] = Field(None, description="Cargo weight in KG")
    cargo_cbm: Optional[float] = Field(None, description="Cargo volume in CBM")
    is_dangerous: Optional[bool] = Field(None, description="Whether the cargo is dangerous goods")
