import logging
from xml.dom.minidom import Element, parseString
from xml.etree.ElementTree import Element, SubElement, tostring

from aiohttp import ClientSession
from dataclasses import dataclass

from user_proxy import config


@dataclass
class HtSMS:
    phone_number: int
    xml: Element = None
    request_node: Element = None

    def __post_init__(self):
        self.xml = self.make_node('soapenv:Envelope', **{
            'xmlns:soapenv': 'http://schemas.xmlsoap.org/soap/envelope/',
            'xmlns:hts': 'http://www.htsec.com/',
        })
        self.xml.append(self.make_node('soapenv:Header'))
        body = self.make_node('soapenv:Body')
        self.xml.append(body)
        self.request_node = self.make_node('hts:request')
        body.append(self.request_node)
        self.request_node.append(
            self.make_node('messageRequestHead', children={
                'consumerCode': config.get_config('soap.consumer_code'),
                'interfaceCode': config.get_config('soap.interface_code'),
                'reqSN': '', 'empCode': '', 'branchCode': '', 'mac': '',
            })
        )

    @staticmethod
    def make_node(name, children=None, **attrs) -> Element:
        children = children or {}
        body = Element(name)
        for key, value in attrs.items():
            body.attrib[key] = value
        for key, value in children.items():
            child = SubElement(body, key)
            child.text = str(value)
        return body

    async def send_msg(self, msg) -> bool:
        self.request_node.append(
            self.make_node('messageRequestBody', children={
                'userName': config.get_config('soap.username'),
                'passWord': config.get_config('soap.password'),
                'subBranch': config.get_config('soap.sub_branch'),
                'productID': config.get_config('soap.product_id'),
                'phone': str(self.phone_number),
                'phoneCount': '1',
                'content': msg,
            })
        )
        xml_bytes = tostring(self.xml)

        headers = {
            'Content-Type': 'text/xml;charset=utf-8',
            'Accept': 'text/xml;charset=utf-8',
        }
        async with ClientSession() as session:
            try:
                response = await session.post(url=config.get_config('soap.uri'), data=xml_bytes, headers=headers)
                xml = parseString(await response.read())
                res_text = await response.text()
                if xml.getElementsByTagName('resultCode')[0].childNodes[0].data != '0':
                    raise Exception(f'系统调用不成功, body: {res_text}')
                return_code = xml.getElementsByTagName('returnCode')[0].childNodes[0].data
                if return_code != '0':
                    raise Exception(f'短信发送失败, 错误码: {return_code}')
            except Exception as e:
                logging.exception(e)
                return False
            return True


if __name__ == '__main__':
    messenger = HtSMS(13265359049)
    assert messenger.send_msg('sss')
